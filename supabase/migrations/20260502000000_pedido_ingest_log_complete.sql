-- =============================================================
-- MIGRATION: pedido_ingest_log estruturado e consultável
-- Data: 2026-05-02
-- Escopo: completar o log de ingest com campos de correlação,
--         stage/status, duração e resumo do payload.
-- =============================================================

ALTER TABLE public.pedido_ingest_log
    ADD COLUMN IF NOT EXISTS correlation_id uuid,
    ADD COLUMN IF NOT EXISTS bling_integration_id int,
    ADD COLUMN IF NOT EXISTS numero_loja text,
    ADD COLUMN IF NOT EXISTS stage text,
    ADD COLUMN IF NOT EXISTS status text,
    ADD COLUMN IF NOT EXISTS message text,
    ADD COLUMN IF NOT EXISTS duration_ms int,
    ADD COLUMN IF NOT EXISTS payload_summary jsonb;

CREATE INDEX IF NOT EXISTS ix_pil_bling_id
    ON public.pedido_ingest_log (bling_id);

CREATE INDEX IF NOT EXISTS ix_pil_numero_loja
    ON public.pedido_ingest_log (numero_loja);

CREATE INDEX IF NOT EXISTS ix_pil_correlation
    ON public.pedido_ingest_log (correlation_id);

CREATE INDEX IF NOT EXISTS ix_pil_pedido_id
    ON public.pedido_ingest_log (pedido_id);

CREATE INDEX IF NOT EXISTS ix_pil_created_at
    ON public.pedido_ingest_log (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_pil_stage
    ON public.pedido_ingest_log (stage);

CREATE INDEX IF NOT EXISTS ix_pil_status
    ON public.pedido_ingest_log (status);
