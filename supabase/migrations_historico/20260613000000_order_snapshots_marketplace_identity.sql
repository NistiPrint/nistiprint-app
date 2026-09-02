-- Canonical order snapshots and marketplace-scoped identity.

CREATE TABLE IF NOT EXISTS public.pedido_snapshots (
    id BIGSERIAL PRIMARY KEY,
    pedido_id INTEGER NOT NULL REFERENCES public.pedidos(id) ON DELETE CASCADE,
    identity JSONB NOT NULL DEFAULT '{}'::jsonb,
    customer JSONB NOT NULL DEFAULT '{}'::jsonb,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    logistics JSONB NOT NULL DEFAULT '{}'::jsonb,
    financial JSONB NOT NULL DEFAULT '{}'::jsonb,
    platform_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.pedido_snapshots
    DROP CONSTRAINT IF EXISTS pedido_snapshots_pedido_id_key;

ALTER TABLE public.pedido_snapshots
    ADD CONSTRAINT pedido_snapshots_pedido_id_key UNIQUE (pedido_id);

ALTER TABLE public.pedidos
    ADD COLUMN IF NOT EXISTS marketplace_order_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS bling_order_id BIGINT,
    ADD COLUMN IF NOT EXISTS bling_order_number VARCHAR(100),
    ADD COLUMN IF NOT EXISTS ingest_source VARCHAR(50);

UPDATE public.pedidos
   SET marketplace_order_id = codigo_pedido_externo
 WHERE marketplace_order_id IS NULL
   AND codigo_pedido_externo IS NOT NULL;

UPDATE public.pedidos p
   SET bling_order_id = pb.bling_id,
       bling_order_number = pb.numero_pedido
  FROM public.pedidos_bling pb
 WHERE p.pedido_bling_id = pb.id
   AND (p.bling_order_id IS NULL OR p.bling_order_number IS NULL);

ALTER TABLE public.pedidos
    DROP CONSTRAINT IF EXISTS pedidos_codigo_pedido_externo_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_marketplace_identity
    ON public.pedidos (marketplace_integration_id, marketplace_order_id)
    WHERE marketplace_integration_id IS NOT NULL
      AND marketplace_order_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pedidos_marketplace_order_id
    ON public.pedidos (marketplace_order_id);

CREATE INDEX IF NOT EXISTS idx_pedido_snapshots_identity_gin
    ON public.pedido_snapshots USING gin (identity);

CREATE INDEX IF NOT EXISTS idx_pedido_snapshots_platform_fields_gin
    ON public.pedido_snapshots USING gin (platform_fields);

ALTER TABLE public.vinculos_integracao_pedido
    DROP CONSTRAINT IF EXISTS vinculos_integracao_pedido_plataforma_id_na_plataforma_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_vinculos_integracao_scoped_external_id
    ON public.vinculos_integracao_pedido (integration_id, plataforma, id_na_plataforma);

INSERT INTO public.pedido_snapshots (
    pedido_id,
    identity,
    customer,
    items,
    logistics,
    financial,
    platform_fields,
    raw_refs,
    source_history
)
SELECT
    p.id,
    jsonb_build_object(
        'ingest_source', COALESCE(p.ingest_source, lower(p.origem)),
        'marketplace_order_id', COALESCE(p.marketplace_order_id, p.codigo_pedido_externo),
        'marketplace_integration_id', p.marketplace_integration_id,
        'bling_integration_id', p.bling_integration_id,
        'bling_order_id', COALESCE(p.bling_order_id, pb.bling_id),
        'bling_order_number', COALESCE(p.bling_order_number, pb.numero_pedido)
    ),
    COALESCE(p.informacoes_cliente, '{}'::jsonb),
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'sku', ip.sku_externo,
            'name', ip.descricao,
            'quantity', ip.quantidade,
            'unit_price', ip.preco_unitario,
            'subtotal', ip.subtotal,
            'produto_id', ip.produto_id
        ) ORDER BY ip.id)
        FROM public.itens_pedido ip
        WHERE ip.pedido_id = p.id
    ), '[]'::jsonb),
    jsonb_build_object(
        'is_flex', p.is_flex,
        'is_fulfillment', p.is_fulfillment,
        'servico_logistico', p.servico_logistico,
        'shipping_carrier', p.shipping_carrier,
        'data_limite_envio', p.data_limite_envio
    ),
    jsonb_build_object(
        'total', p.total_pedido,
        'currency', p.moeda
    ),
    jsonb_build_object(
        'buyer_username', p.buyer_username,
        'message_to_seller', p.message_to_seller,
        'shipping_carrier', p.shipping_carrier
    ),
    jsonb_build_object(
        'pedido_bling_id', p.pedido_bling_id,
        'pedido_shopee_id', p.pedido_shopee_id,
        'pedido_mercadolivre_id', p.pedido_mercadolivre_id
    ),
    jsonb_build_array(jsonb_build_object(
        'source', COALESCE(p.ingest_source, lower(p.origem)),
        'at', now(),
        'backfill', true
    ))
FROM public.pedidos p
LEFT JOIN public.pedidos_bling pb ON pb.id = p.pedido_bling_id
ON CONFLICT (pedido_id) DO NOTHING;

GRANT ALL ON TABLE public.pedido_snapshots TO anon;
GRANT ALL ON TABLE public.pedido_snapshots TO authenticated;
GRANT ALL ON TABLE public.pedido_snapshots TO service_role;
GRANT ALL ON SEQUENCE public.pedido_snapshots_id_seq TO anon;
GRANT ALL ON SEQUENCE public.pedido_snapshots_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.pedido_snapshots_id_seq TO service_role;
