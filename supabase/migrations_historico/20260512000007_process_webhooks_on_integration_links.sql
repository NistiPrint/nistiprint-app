-- Controla se webhooks recebidos por um vinculo Bling/loja/marketplace
-- devem ser processados ou apenas auditados como ignorados.

ALTER TABLE public.channel_connections
  ADD COLUMN IF NOT EXISTS process_webhooks boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN public.channel_connections.process_webhooks IS
  'Quando false, webhooks do Bling para este vínculo ativo são ignorados pelo worker';

ALTER TABLE public.erp_marketplace_links
  ADD COLUMN IF NOT EXISTS process_webhooks boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN public.erp_marketplace_links.process_webhooks IS
  'Mantem a preferencia de processamento de webhooks sincronizada com channel_connections';

DROP INDEX IF EXISTS public.idx_channel_connections_channel_aggregator;

CREATE INDEX IF NOT EXISTS idx_channel_connections_webhook_processing
  ON public.channel_connections (bling_integration_id, aggregator_store_id, process_webhooks)
  WHERE is_active = true
    AND bling_integration_id IS NOT NULL
    AND aggregator_store_id IS NOT NULL;
