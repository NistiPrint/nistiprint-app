-- Fix view_vendas_personalizadas_v3 to include client name and personalizations data
-- 1. Client name: Extract from pedidos_shopee.informacoes_comprador->>'name' and include in contato
-- 2. Personalizations: Join with personalizacoes_pedido table to include customization data in items

DROP VIEW IF EXISTS view_vendas_personalizadas_v3;

CREATE VIEW view_vendas_personalizadas_v3 AS
SELECT
    p.id,
    p.numero_pedido,
    p.codigo_pedido_externo AS numero_loja,
    p.data_venda AS data_pedido,
    -- Build contato object with name from pedidos_bling.nome_cliente
    jsonb_build_object(
        'nome', pb.nome_cliente,
        'email', pb.email_cliente,
        'telefone', pb.telefone_cliente
    ) AS contato,
    p.is_flex,
    v_bling.id_na_plataforma AS bling_id,
    true AS personalizado,
    false AS deletado,
    -- buyer_username from pedidos_shopee only
    ps.informacoes_comprador::jsonb->>'username' AS buyer_username,
    ps.mensagem AS shopee_message,
    ps.shipping_carrier,
    -- Chat messages using buyer_username
    (EXISTS (
        SELECT 1 FROM mensagem_chat_shopee mcs
        WHERE mcs.from_user_name = ps.informacoes_comprador::jsonb->>'username'
           OR mcs.to_user_name = ps.informacoes_comprador::jsonb->>'username'
    )) AS has_chat_messages,
    -- Items (only personalized items) with personalizations data
    COALESCE((
        SELECT jsonb_agg(
            jsonb_build_object(
                'id', ip.id,
                'codigo', ip.sku_externo,
                'descricao', ip.descricao,
                'quantidade', ip.quantidade,
                'valor', ip.preco_unitario,
                'unidade', 'UN',
                'personalizado', ip.personalizado,
                'produto', jsonb_build_object('id', ip.produto_id),
                -- Personalizations array from personalizacoes_pedido table
                'personalizations', COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'id', pp.id,
                            'customization_name', pp.customization_name,
                            'customization_initial', pp.customization_initial,
                            'quantity_to_personalize', pp.detalhes_personalizacao::jsonb->>'quantity_to_personalize',
                            'status', pp.status,
                            'reasoning', pp.reasoning,
                            'name_source_message_id', pp.name_source_message_id,
                            'initial_source_message_id', pp.detalhes_personalizacao::jsonb->>'initial_source_message_id'
                        )
                    )
                    FROM personalizacoes_pedido pp
                    WHERE pp.item_pedido_id = ip.id
                ), '[]'::jsonb)
            )
        )
        FROM itens_pedido ip WHERE ip.pedido_id = p.id AND ip.personalizado = true
    ), '[]'::jsonb) AS itens
FROM pedidos p
INNER JOIN canais_venda cv ON p.canal_venda_id = cv.id
INNER JOIN pedidos_shopee ps ON p.codigo_pedido_externo = ps.codigo_pedido
LEFT JOIN pedidos_bling pb ON p.numero_pedido = pb.numero_pedido
LEFT JOIN vinculos_integracao_pedido v_bling ON p.id = v_bling.pedido_id AND v_bling.plataforma = 'BLING'
WHERE cv.slug = 'shopee'
  AND EXISTS (
      SELECT 1 FROM itens_pedido ip
      WHERE ip.pedido_id = p.id AND ip.personalizado = true
  );
