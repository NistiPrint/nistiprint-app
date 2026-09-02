-- =============================================================
-- MIGRATION: monitoramento persistente de webhooks Bling
-- Escopo: tentativas por evento, indices de consulta e bloqueio
--         de acesso direto a payload bruto fora do backend.
-- =============================================================

ALTER TABLE public.webhook_events
    ALTER COLUMN source SET DEFAULT 'bling';

CREATE INDEX IF NOT EXISTS ix_webhook_events_source
    ON public.webhook_events (source);

CREATE INDEX IF NOT EXISTS ix_webhook_events_last_status
    ON public.webhook_events (last_status);

CREATE INDEX IF NOT EXISTS ix_webhook_events_last_attempt_at
    ON public.webhook_events (last_attempt_at DESC);

CREATE INDEX IF NOT EXISTS ix_webhook_events_source_status_attempt
    ON public.webhook_events (source, last_status, last_attempt_at DESC);

CREATE TABLE IF NOT EXISTS public.webhook_event_attempts (
    id BIGSERIAL PRIMARY KEY,
    webhook_event_id BIGINT NOT NULL REFERENCES public.webhook_events(id) ON DELETE CASCADE,
    correlation_id UUID NOT NULL,
    attempt_number INT NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing',
    queue_name TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    error_type TEXT,
    error_message TEXT,
    result_summary JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_webhook_event_attempts_event_id
    ON public.webhook_event_attempts (webhook_event_id, started_at DESC);

CREATE INDEX IF NOT EXISTS ix_webhook_event_attempts_correlation_id
    ON public.webhook_event_attempts (correlation_id);

CREATE INDEX IF NOT EXISTS ix_webhook_event_attempts_status
    ON public.webhook_event_attempts (status);

ALTER TABLE public.webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_event_attempts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.webhook_events FROM anon;
REVOKE ALL ON TABLE public.webhook_events FROM authenticated;
REVOKE ALL ON SEQUENCE public.webhook_events_id_seq FROM anon;
REVOKE ALL ON SEQUENCE public.webhook_events_id_seq FROM authenticated;

REVOKE ALL ON TABLE public.webhook_event_attempts FROM anon;
REVOKE ALL ON TABLE public.webhook_event_attempts FROM authenticated;
REVOKE ALL ON SEQUENCE public.webhook_event_attempts_id_seq FROM anon;
REVOKE ALL ON SEQUENCE public.webhook_event_attempts_id_seq FROM authenticated;

GRANT ALL ON TABLE public.webhook_events TO service_role;
GRANT ALL ON SEQUENCE public.webhook_events_id_seq TO service_role;
GRANT ALL ON TABLE public.webhook_event_attempts TO service_role;
GRANT ALL ON SEQUENCE public.webhook_event_attempts_id_seq TO service_role;
