-- Reliable webhook acceptance, idempotency, signature audit and archive manifests.
ALTER TABLE public.webhook_events
  ADD COLUMN IF NOT EXISTS dedupe_scope text,
  ADD COLUMN IF NOT EXISTS dedupe_key text,
  ADD COLUMN IF NOT EXISTS delivery_count integer NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS last_received_at timestamptz,
  ADD COLUMN IF NOT EXISTS raw_body text,
  ADD COLUMN IF NOT EXISTS signature_status text,
  ADD COLUMN IF NOT EXISTS signature_checked_at timestamptz,
  ADD COLUMN IF NOT EXISTS signature_error text,
  ADD COLUMN IF NOT EXISTS raw_archived_at timestamptz,
  ADD COLUMN IF NOT EXISTS archive_object_key text;

UPDATE public.webhook_events
SET dedupe_scope = COALESCE(dedupe_scope, NULLIF(company_id, ''), 'source'),
    dedupe_key = COALESCE(dedupe_key,
      CASE WHEN provider_event_id IS NOT NULL THEN 'provider:' || provider_event_id
           WHEN payload_hash IS NOT NULL THEN 'sha256:' || payload_hash
           ELSE 'legacy:' || id::text END),
    last_received_at = COALESCE(last_received_at, received_at);

-- Preserve old rows even where a provider historically reused an identifier.
WITH duplicates AS (
  SELECT id, row_number() OVER (
    PARTITION BY source, dedupe_scope, dedupe_key ORDER BY id
  ) AS occurrence
  FROM public.webhook_events
)
UPDATE public.webhook_events event
SET dedupe_key = event.dedupe_key || ':legacy-' || duplicates.occurrence::text
FROM duplicates
WHERE duplicates.id = event.id AND duplicates.occurrence > 1;

ALTER TABLE public.webhook_events
  ALTER COLUMN dedupe_scope SET DEFAULT 'source',
  ALTER COLUMN dedupe_scope SET NOT NULL,
  ALTER COLUMN dedupe_key SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_events_dedupe
  ON public.webhook_events (source, dedupe_scope, dedupe_key);
CREATE INDEX IF NOT EXISTS ix_webhook_events_backlog
  ON public.webhook_events (last_status, next_attempt_after, received_at)
  WHERE last_status IN ('pending', 'accepted', 'pending_retry', 'processing');

CREATE TABLE IF NOT EXISTS public.archive_manifests (
  id bigserial PRIMARY KEY,
  dataset text NOT NULL,
  period_start date NOT NULL,
  period_end date NOT NULL,
  object_key text NOT NULL,
  row_count bigint NOT NULL CHECK (row_count >= 0),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version > 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (dataset, object_key)
);
ALTER TABLE public.archive_manifests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.archive_manifests FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.archive_manifests TO service_role;
GRANT ALL ON SEQUENCE public.archive_manifests_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public.accept_reliable_webhook_event(
  p_source text,
  p_dedupe_scope text,
  p_dedupe_key text,
  p_provider_event_id text,
  p_payload_hash text,
  p_raw_payload jsonb,
  p_raw_body text,
  p_received_at timestamptz,
  p_correlation_id uuid,
  p_resolved_order_id text DEFAULT NULL
)
RETURNS TABLE(webhook_event_id bigint, created boolean, should_process boolean)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  accepted_id bigint;
BEGIN
  INSERT INTO public.webhook_events (
    source, dedupe_scope, dedupe_key, provider_event_id, payload_hash,
    raw_payload, raw_body, received_at, last_received_at, correlation_id,
    resolved_order_id, last_status, retry_expires_at
  ) VALUES (
    lower(trim(p_source)), COALESCE(NULLIF(p_dedupe_scope, ''), 'source'),
    p_dedupe_key, p_provider_event_id, p_payload_hash,
    COALESCE(p_raw_payload, '{}'::jsonb), p_raw_body,
    COALESCE(p_received_at, now()), COALESCE(p_received_at, now()),
    p_correlation_id, p_resolved_order_id, 'accepted', now() + interval '7 days'
  )
  ON CONFLICT (source, dedupe_scope, dedupe_key) DO NOTHING
  RETURNING id INTO accepted_id;

  IF accepted_id IS NOT NULL THEN
    RETURN QUERY SELECT accepted_id, true, true;
    RETURN;
  END IF;

  UPDATE public.webhook_events
  SET delivery_count = delivery_count + 1,
      last_received_at = GREATEST(
        COALESCE(last_received_at, received_at), COALESCE(p_received_at, now())
      )
  WHERE source = lower(trim(p_source))
    AND dedupe_scope = COALESCE(NULLIF(p_dedupe_scope, ''), 'source')
    AND dedupe_key = p_dedupe_key
  RETURNING id INTO accepted_id;

  RETURN QUERY SELECT accepted_id, false, false;
END;
$$;

REVOKE ALL ON FUNCTION public.accept_reliable_webhook_event(
  text, text, text, text, text, jsonb, text, timestamptz, uuid, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_reliable_webhook_event(
  text, text, text, text, text, jsonb, text, timestamptz, uuid, text
) TO service_role;

ALTER TABLE public.webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_event_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.webhook_events FROM anon, authenticated;
REVOKE ALL ON TABLE public.webhook_event_attempts FROM anon, authenticated;
GRANT ALL ON TABLE public.webhook_events TO service_role;
GRANT ALL ON TABLE public.webhook_event_attempts TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.webhook_events_id_seq TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.webhook_event_attempts_id_seq TO service_role;
