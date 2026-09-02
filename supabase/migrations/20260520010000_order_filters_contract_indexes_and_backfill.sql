-- Improve order filters performance and integrity for list-advanced endpoint.

-- Core filter indexes
CREATE INDEX IF NOT EXISTS idx_pedidos_situacao_pedido_id
    ON public.pedidos (situacao_pedido_id);

CREATE INDEX IF NOT EXISTS idx_pedidos_data_venda
    ON public.pedidos (data_venda);

CREATE INDEX IF NOT EXISTS idx_pedidos_data_limite_envio
    ON public.pedidos (data_limite_envio);

CREATE INDEX IF NOT EXISTS idx_pedidos_canal_venda_id
    ON public.pedidos (canal_venda_id);

CREATE INDEX IF NOT EXISTS idx_pedidos_marketplace_integration_id
    ON public.pedidos (marketplace_integration_id);

CREATE INDEX IF NOT EXISTS idx_pedidos_bling_integration_id
    ON public.pedidos (bling_integration_id);

CREATE INDEX IF NOT EXISTS idx_pedidos_flags_logistica
    ON public.pedidos (is_flex, is_fulfillment, personalizado);

-- Origin and demand support indexes
CREATE INDEX IF NOT EXISTS idx_pedidos_bling_loja_id
    ON public.pedidos_bling (loja_id);

CREATE INDEX IF NOT EXISTS idx_demandas_pedidos_pedido_id
    ON public.demandas_pedidos (pedido_id);

CREATE INDEX IF NOT EXISTS idx_channel_connections_origin_lookup
    ON public.channel_connections (aggregator_store_id, bling_integration_id, marketplace_integration_id)
    WHERE is_active = true;

-- Backfill missing pedido_bling_id when external code matches pedidos_bling.codigo_pedido.
UPDATE public.pedidos p
SET pedido_bling_id = pb.id,
    updated_at = now()
FROM public.pedidos_bling pb
WHERE p.pedido_bling_id IS NULL
  AND p.codigo_pedido_externo IS NOT NULL
  AND pb.codigo_pedido = p.codigo_pedido_externo;
