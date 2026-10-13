CREATE TABLE IF NOT EXISTS public.shopee_order_resync_checkpoints (
    integration_id integer NOT NULL REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
    window_from bigint NOT NULL,
    window_to bigint NOT NULL,
    order_status text NOT NULL,
    next_cursor text,
    completed boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (integration_id, window_from, window_to, order_status),
    CHECK (window_from < window_to),
    CHECK (order_status IN ('UNPAID', 'READY_TO_SHIP', 'PROCESSED', 'RETRY_SHIP', 'SHIPPED', 'TO_CONFIRM_RECEIVE'))
);

ALTER TABLE public.shopee_order_resync_checkpoints ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.shopee_order_resync_checkpoints FROM anon, authenticated;
GRANT ALL ON public.shopee_order_resync_checkpoints TO service_role;

COMMENT ON TABLE public.shopee_order_resync_checkpoints IS
    'Checkpoint por conta, janela e estado da paginação histórica Shopee; atualizado após cada página processada.';
