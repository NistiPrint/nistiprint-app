-- =============================================================
-- MIGRATION: preserva webhook original para reprocessamento
-- Data: 2026-05-05
-- Escopo: armazenar snapshot bruto do webhook Bling por pedido
--         e permitir reenfileiramento auditavel.
-- =============================================================

CREATE TABLE IF NOT EXISTS public.webhook_events (
    id BIGSERIAL PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT NOT NULL,
    company_id TEXT,
    bling_id BIGINT,
    numero_loja TEXT,
    raw_payload JSONB NOT NULL,
    correlation_id UUID NOT NULL,
    pedido_id BIGINT REFERENCES public.pedidos(id) ON DELETE SET NULL,
    last_status TEXT,
    last_attempt_at TIMESTAMPTZ,
    attempt_count INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_webhook_events_bling_id
    ON public.webhook_events (bling_id);

CREATE INDEX IF NOT EXISTS ix_webhook_events_numero_loja
    ON public.webhook_events (numero_loja);

CREATE INDEX IF NOT EXISTS ix_webhook_events_pedido_id
    ON public.webhook_events (pedido_id);

CREATE INDEX IF NOT EXISTS ix_webhook_events_correlation_id
    ON public.webhook_events (correlation_id);

CREATE INDEX IF NOT EXISTS ix_webhook_events_received_at
    ON public.webhook_events (received_at DESC);

GRANT ALL ON TABLE public.webhook_events TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.webhook_events TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.webhook_events TO anon;
GRANT ALL ON SEQUENCE public.webhook_events_id_seq TO service_role;
GRANT ALL ON SEQUENCE public.webhook_events_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.webhook_events_id_seq TO anon;
