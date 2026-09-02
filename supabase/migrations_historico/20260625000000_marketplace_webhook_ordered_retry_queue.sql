-- =============================================================
-- MIGRATION: fila logica ordenada por pedido para webhooks de marketplace
-- Escopo: manter retry no mesmo evento, bloquear apenas o mesmo pedido
--         e expirar para intervencao manual sem mover para outra fila.
-- =============================================================

ALTER TABLE public.webhook_events
    ADD COLUMN IF NOT EXISTS provider_event_id TEXT,
    ADD COLUMN IF NOT EXISTS payload_hash TEXT,
    ADD COLUMN IF NOT EXISTS next_attempt_after TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_correlation_id UUID,
    ADD COLUMN IF NOT EXISTS last_error_type TEXT,
    ADD COLUMN IF NOT EXISTS last_error_message TEXT,
    ADD COLUMN IF NOT EXISTS retry_expires_at TIMESTAMPTZ;

UPDATE public.webhook_events
SET retry_expires_at = COALESCE(retry_expires_at, received_at + INTERVAL '7 days')
WHERE retry_expires_at IS NULL;

ALTER TABLE public.webhook_events
    ALTER COLUMN retry_expires_at SET DEFAULT (NOW() + INTERVAL '7 days');

CREATE INDEX IF NOT EXISTS ix_webhook_events_source_retry_window
    ON public.webhook_events (source, last_status, next_attempt_after, received_at);

CREATE INDEX IF NOT EXISTS ix_webhook_events_source_order_received
    ON public.webhook_events (source, company_id, numero_loja, received_at);

CREATE INDEX IF NOT EXISTS ix_webhook_events_provider_event_id
    ON public.webhook_events (source, provider_event_id)
    WHERE provider_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_webhook_events_payload_hash
    ON public.webhook_events (source, payload_hash);
