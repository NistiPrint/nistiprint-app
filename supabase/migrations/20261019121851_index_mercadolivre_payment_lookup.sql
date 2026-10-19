-- Payment webhooks resolve their order with raw_order @> {"payments": [{"id": ...}]}.
-- A GIN path index avoids reading every stored order JSON document on a miss.
CREATE INDEX IF NOT EXISTS ix_pedidos_mercadolivre_raw_order_path
    ON public.pedidos_mercadolivre USING gin (raw_order jsonb_path_ops);
