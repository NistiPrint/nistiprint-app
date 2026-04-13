-- Migração para reclassificar pedidos Flex baseado em shipping_carrier
-- Atualiza is_flex baseado no shipping_carrier dos dados do marketplace (Shopee)

-- Atualizar pedidos com shipping_carrier contendo "Entrega Rápida" para is_flex=true
UPDATE pedidos p
SET is_flex = true,
    servico_logistico = COALESCE(
        (v_shopee.dados_brutos->>'shipping_carrier'),
        p.servico_logistico
    ),
    updated_at = NOW()
FROM vinculos_integracao_pedido v_shopee
WHERE p.id = v_shopee.pedido_id
  AND v_shopee.plataforma = 'SHOPEE'
  AND v_shopee.dados_brutos->>'shipping_carrier' IS NOT NULL
  AND (
    UPPER(v_shopee.dados_brutos->>'shipping_carrier') LIKE '%ENTREGA RÁPIDA%' OR
    UPPER(v_shopee.dados_brutos->>'shipping_carrier') LIKE '%ENTREGA RAPIDA%'
  )
  AND p.is_flex = false;

-- Atualizar servico_logistico para pedidos que têm dados do marketplace mas não têm shipping_carrier definido
UPDATE pedidos p
SET servico_logistico = COALESCE(
        (v_shopee.dados_brutos->>'shipping_carrier'),
        p.servico_logistico
    ),
    updated_at = NOW()
FROM vinculos_integracao_pedido v_shopee
WHERE p.id = v_shopee.pedido_id
  AND v_shopee.plataforma = 'SHOPEE'
  AND v_shopee.dados_brutos->>'shipping_carrier' IS NOT NULL
  AND (p.servico_logistico IS NULL OR p.servico_logistico = '');

-- Log de quantos pedidos foram reclassificados
-- (Execute separadamente para ver o resultado)
-- SELECT COUNT(*) as pedidos_reclassificados FROM pedidos WHERE is_flex = true AND canal_venda_id = 1;
