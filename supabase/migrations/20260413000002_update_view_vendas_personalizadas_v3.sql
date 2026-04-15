-- Update view_vendas_personalizadas_v3 to use data from pedidos_shopee directly
-- This ensures buyer_username, shopee_message, and shipping_carrier come from the source of truth
-- Platform identification uses canal_venda.slug instead of pedido.origem for accuracy

DROP VIEW IF EXISTS view_vendas_personalizadas_v3;

CREATE VIEW view_vendas_personalizadas_v3 AS
SELECT
    p.id,
    p.numero_pedido,
    p.codigo_pedido_externo AS numero_loja,
    p.data_venda AS data_pedido,
    p.informacoes_cliente AS contato,
    p.is_flex,
    v_bling.id_na_plataforma AS bling_id,
    true AS personalizado,
    false AS deletado,
    -- buyer_username from pedidos_shopee only - NO FALLBACK to client name
    ps.informacoes_comprador::jsonb->>'username' AS buyer_username,
    ps.mensagem AS shopee_message,
    ps.shipping_carrier,
    -- Chat messages using buyer_username
    (EXISTS (
        SELECT 1 FROM mensagem_chat_shopee mcs
        WHERE mcs.from_user_name = ps.informacoes_comprador::jsonb->>'username'
           OR mcs.to_user_name = ps.informacoes_comprador::jsonb->>'username'
    )) AS has_chat_messages,
    -- Items (only personalized items)
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'id', ip.id,
            'codigo', ip.sku_externo,
            'descricao', ip.descricao,
            'quantidade', ip.quantidade,
            'valor', ip.preco_unitario,
            'unidade', 'UN',
            'personalizado', ip.personalizado,
            'produto', jsonb_build_object('id', ip.produto_id)
        ))
        FROM itens_pedido ip WHERE ip.pedido_id = p.id AND ip.personalizado = true
    ), '[]'::jsonb) AS itens
FROM pedidos p
INNER JOIN canais_venda cv ON p.canal_venda_id = cv.id
INNER JOIN pedidos_shopee ps ON p.codigo_pedido_externo = ps.codigo_pedido
LEFT JOIN vinculos_integracao_pedido v_bling ON p.id = v_bling.pedido_id AND v_bling.plataforma = 'BLING'
WHERE cv.slug = 'shopee'
  AND EXISTS (
      SELECT 1 FROM itens_pedido ip
      WHERE ip.pedido_id = p.id AND ip.personalizado = true
  );
