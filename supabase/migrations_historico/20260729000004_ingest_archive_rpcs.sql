-- Service-role-only archive batches. Data is mutated only after the worker
-- confirms the compressed object and supplies its checksum.
ALTER TABLE public.mensagem_chat_shopee
  ADD COLUMN IF NOT EXISTS raw_archived_at timestamptz,
  ADD COLUMN IF NOT EXISTS archive_object_key text;

CREATE OR REPLACE FUNCTION public.get_ingest_archive_batch(
  p_dataset text,
  p_before timestamptz,
  p_limit integer DEFAULT 1000
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  result jsonb;
  batch_limit integer := LEAST(GREATEST(COALESCE(p_limit, 1000), 1), 5000);
BEGIN
  CASE p_dataset
    WHEN 'webhook_payloads' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.received_at, row_data.id), '[]'::jsonb)
      INTO result
      FROM (
        SELECT * FROM public.webhook_events
        WHERE received_at < p_before
          AND raw_archived_at IS NULL
          AND (raw_body IS NOT NULL OR raw_payload <> '{}'::jsonb)
          AND last_status NOT IN ('pending', 'accepted', 'pending_retry', 'processing', 'manual_intervention')
        ORDER BY received_at, id LIMIT batch_limit
      ) row_data;
    WHEN 'shopee_chat_payloads' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.event_time, row_data.id), '[]'::jsonb)
      INTO result
      FROM (
        SELECT message.*,
               COALESCE(message.received_at, message.created_timestamp,
                        message.created_at AT TIME ZONE 'UTC') AS event_time
        FROM public.mensagem_chat_shopee message
        WHERE COALESCE(message.received_at, message.created_timestamp,
                       message.created_at AT TIME ZONE 'UTC') < p_before
          AND message.raw_archived_at IS NULL
          AND (message.raw_json IS NOT NULL OR message.raw_payload IS NOT NULL)
        ORDER BY event_time, message.id LIMIT batch_limit
      ) row_data;
    WHEN 'webhook_event_attempts' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.created_at, row_data.id), '[]'::jsonb)
      INTO result
      FROM (
        SELECT attempt.* FROM public.webhook_event_attempts attempt
        JOIN public.webhook_events event ON event.id = attempt.webhook_event_id
        WHERE attempt.created_at < p_before
          AND event.last_status NOT IN ('pending', 'accepted', 'pending_retry', 'processing', 'manual_intervention')
        ORDER BY attempt.created_at, attempt.id LIMIT batch_limit
      ) row_data;
    WHEN 'task_execution_logs' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.created_at, row_data.id), '[]'::jsonb)
      INTO result FROM (
        SELECT * FROM public.task_execution_logs
        WHERE created_at < p_before ORDER BY created_at, id LIMIT batch_limit
      ) row_data;
    WHEN 'pedido_ingest_log' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.created_at, row_data.id), '[]'::jsonb)
      INTO result FROM (
        SELECT * FROM public.pedido_ingest_log
        WHERE created_at < p_before ORDER BY created_at, id LIMIT batch_limit
      ) row_data;
    WHEN 'integration_refresh_logs' THEN
      SELECT COALESCE(jsonb_agg(to_jsonb(row_data) ORDER BY row_data.created_at, row_data.id), '[]'::jsonb)
      INTO result FROM (
        SELECT * FROM public.integration_refresh_logs
        WHERE (lower(status) IN ('success', 'completed', 'ok') AND created_at < p_before)
           OR (lower(status) NOT IN ('success', 'completed', 'ok') AND created_at < p_before - interval '23 days')
        ORDER BY created_at, id LIMIT batch_limit
      ) row_data;
    ELSE
      RAISE EXCEPTION 'unsupported archive dataset: %', p_dataset;
  END CASE;
  RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_ingest_archive_batch(
  p_dataset text,
  p_ids text[],
  p_object_key text,
  p_sha256 text,
  p_period_start date,
  p_period_end date,
  p_row_count bigint,
  p_schema_version integer DEFAULT 1
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE manifest_id bigint;
BEGIN
  IF COALESCE(array_length(p_ids, 1), 0) = 0 THEN
    RAISE EXCEPTION 'archive batch cannot be empty';
  END IF;
  IF p_row_count <> array_length(p_ids, 1) THEN
    RAISE EXCEPTION 'row count does not match id count';
  END IF;

  INSERT INTO public.archive_manifests (
    dataset, period_start, period_end, object_key, row_count, sha256, schema_version
  ) VALUES (
    p_dataset, p_period_start, p_period_end, p_object_key, p_row_count, p_sha256,
    COALESCE(p_schema_version, 1)
  )
  ON CONFLICT (dataset, object_key) DO NOTHING
  RETURNING id INTO manifest_id;

  IF manifest_id IS NULL THEN
    SELECT id INTO manifest_id FROM public.archive_manifests
    WHERE dataset = p_dataset AND object_key = p_object_key
      AND sha256 = p_sha256 AND row_count = p_row_count;
    IF manifest_id IS NULL THEN
      RAISE EXCEPTION 'archive manifest conflict for %', p_object_key;
    END IF;
  END IF;

  CASE p_dataset
    WHEN 'webhook_payloads' THEN
      UPDATE public.webhook_events
      SET raw_payload = '{}'::jsonb, raw_body = NULL, raw_archived_at = now(),
          archive_object_key = p_object_key
      WHERE id = ANY(p_ids::bigint[]) AND raw_archived_at IS NULL;
    WHEN 'shopee_chat_payloads' THEN
      UPDATE public.mensagem_chat_shopee
      SET raw_json = NULL, raw_payload = NULL, raw_archived_at = now(),
          archive_object_key = p_object_key
      WHERE id = ANY(p_ids) AND raw_archived_at IS NULL;
    WHEN 'webhook_event_attempts' THEN
      DELETE FROM public.webhook_event_attempts WHERE id = ANY(p_ids::bigint[]);
    WHEN 'task_execution_logs' THEN
      DELETE FROM public.task_execution_logs WHERE id = ANY(p_ids::uuid[]);
    WHEN 'pedido_ingest_log' THEN
      DELETE FROM public.pedido_ingest_log WHERE id = ANY(p_ids::bigint[]);
    WHEN 'integration_refresh_logs' THEN
      DELETE FROM public.integration_refresh_logs WHERE id = ANY(p_ids::integer[]);
    ELSE
      RAISE EXCEPTION 'unsupported archive dataset: %', p_dataset;
  END CASE;
  RETURN manifest_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.cleanup_archived_ingest_hot_data(p_limit integer DEFAULT 1000)
RETURNS TABLE(chat_deleted integer, events_deleted integer)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE deleted_chat integer := 0; deleted_events integer := 0;
BEGIN
  WITH candidates AS (
    SELECT message.id FROM public.mensagem_chat_shopee message
    WHERE message.raw_archived_at IS NOT NULL
      AND COALESCE(message.received_at, message.created_timestamp,
                   message.created_at AT TIME ZONE 'UTC') < now() - interval '30 days'
      AND NOT EXISTS (
        SELECT 1 FROM public.grupo_mensagens_chat_shopee bundle
        WHERE bundle.event_id = message.id
      )
    ORDER BY message.id LIMIT LEAST(GREATEST(COALESCE(p_limit, 1000), 1), 5000)
  )
  DELETE FROM public.mensagem_chat_shopee message
  USING candidates WHERE message.id = candidates.id;
  GET DIAGNOSTICS deleted_chat = ROW_COUNT;

  WITH candidates AS (
    SELECT id FROM public.webhook_events
    WHERE raw_archived_at IS NOT NULL
      AND received_at < now() - interval '30 days'
      AND last_status NOT IN ('pending', 'accepted', 'pending_retry', 'processing', 'manual_intervention')
    ORDER BY id LIMIT LEAST(GREATEST(COALESCE(p_limit, 1000), 1), 5000)
  )
  DELETE FROM public.webhook_events event
  USING candidates WHERE event.id = candidates.id;
  GET DIAGNOSTICS deleted_events = ROW_COUNT;
  RETURN QUERY SELECT deleted_chat, deleted_events;
END;
$$;

REVOKE ALL ON FUNCTION public.get_ingest_archive_batch(text, timestamptz, integer)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.finalize_ingest_archive_batch(text, text[], text, text, date, date, bigint, integer)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.cleanup_archived_ingest_hot_data(integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_ingest_archive_batch(text, timestamptz, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.finalize_ingest_archive_batch(text, text[], text, text, date, date, bigint, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.cleanup_archived_ingest_hot_data(integer) TO service_role;
