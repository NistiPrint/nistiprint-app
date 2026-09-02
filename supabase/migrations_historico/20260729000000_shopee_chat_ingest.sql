-- Idempotent SellerChat ingestion and provider-level deduplication.
ALTER TABLE public.mensagem_chat_shopee
  ADD COLUMN IF NOT EXISTS installed_integration_id bigint REFERENCES public.installed_integrations(id),
  ADD COLUMN IF NOT EXISTS provider_message_id text,
  ADD COLUMN IF NOT EXISTS webhook_event_id bigint REFERENCES public.webhook_events(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS ingestion_source text NOT NULL DEFAULT 'legacy',
  ADD COLUMN IF NOT EXISTS received_at timestamptz NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS raw_payload jsonb,
  ADD COLUMN IF NOT EXISTS business_type smallint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS region text,
  ADD COLUMN IF NOT EXISTS is_in_chatbot_session boolean,
  ADD COLUMN IF NOT EXISTS quoted_msg jsonb,
  ADD COLUMN IF NOT EXISTS sub_account_id bigint,
  ADD COLUMN IF NOT EXISTS sub_account_name text,
  ADD COLUMN IF NOT EXISTS shopee_chatbot_replied boolean;

-- Legacy chat rows used shop_id=0. Backfill only when the project has exactly
-- one active Shopee integration, avoiding any generated-ID assumptions.
WITH active_shopee AS (
  SELECT ii.id,
         COALESCE(
           NULLIF(ii.config->>'shop_id', ''),
           NULLIF(ii.credentials->>'shop_id', ''),
           NULLIF(ii.config->'account_identifiers'->>'primary', '')
         ) AS shop_id
  FROM public.installed_integrations ii
  JOIN public.integration_modules im ON im.id = ii.module_id
  WHERE im.slug = 'shopee' AND ii.is_active = true
), single_shopee AS (
  SELECT min(id) AS id, min(shop_id) AS shop_id
  FROM active_shopee
  HAVING count(*) = 1
)
UPDATE public.mensagem_chat_shopee message
SET installed_integration_id = account.id,
    provider_message_id = message.id,
    shop_id = CASE
      WHEN message.shop_id IS NULL OR message.shop_id = 0
        THEN account.shop_id::bigint
      ELSE message.shop_id
    END
FROM single_shopee account
WHERE message.installed_integration_id IS NULL
  AND account.id IS NOT NULL;

DROP INDEX IF EXISTS public.uq_mensagem_chat_shopee_provider_message;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mensagem_chat_shopee_provider_message
  ON public.mensagem_chat_shopee (installed_integration_id, provider_message_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_events_shopee_provider_event
  ON public.webhook_events (source, provider_event_id)
  WHERE source = 'shopee' AND provider_resource = 'chat_message'
    AND provider_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mensagem_chat_shopee_conversation_ingest
  ON public.mensagem_chat_shopee (installed_integration_id, conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mensagem_chat_shopee_received_at
  ON public.mensagem_chat_shopee (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_mensagem_chat_shopee_webhook_event_id
  ON public.mensagem_chat_shopee (webhook_event_id)
  WHERE webhook_event_id IS NOT NULL;

-- Remove legacy duplicates while retaining idx_chat_* equivalents.
DROP INDEX IF EXISTS public.idx_mensagem_chat_shopee_created_at_desc;
DROP INDEX IF EXISTS public.idx_mensagem_chat_shopee_from_user;
DROP INDEX IF EXISTS public.idx_mensagem_chat_shopee_to_user;

COMMENT ON COLUMN public.mensagem_chat_shopee.provider_message_id IS
  'ID imutavel da mensagem no SellerChat; usado para idempotencia.';
COMMENT ON COLUMN public.mensagem_chat_shopee.raw_payload IS
  'Payload bruto recebido ou retornado pela API SellerChat para auditoria.';

ALTER TABLE public.mensagem_chat_shopee ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON public.mensagem_chat_shopee FROM anon, authenticated;
GRANT SELECT ON public.mensagem_chat_shopee TO authenticated;
GRANT ALL ON public.mensagem_chat_shopee TO service_role;
