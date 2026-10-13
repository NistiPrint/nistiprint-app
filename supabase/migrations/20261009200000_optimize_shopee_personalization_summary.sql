-- Aggregate personalized items only for orders in the Shopee personalized view.
-- The previous view aggregated every personalized order once per output order,
-- making summary counts scan the full item/personalization set repeatedly.
CREATE OR REPLACE VIEW public.view_pedidos_personalizados_ai
WITH (security_invoker = true) AS
WITH base_orders AS (
    SELECT
        p.id,
        p.numero_pedido,
        p.codigo_pedido_externo AS numero_loja,
        p.data_venda AS data_pedido,
        COALESCE(p.informacoes_cliente, '{}'::jsonb) AS contato,
        COALESCE(
            NULLIF(trim(p.cliente_nome), ''),
            NULLIF(trim(p.informacoes_cliente ->> 'nome'), ''),
            NULLIF(trim(p.informacoes_cliente ->> 'name'), ''),
            NULLIF(trim(p.buyer_username), ''),
            p.codigo_pedido_externo
        ) AS nome_cliente,
        p.buyer_username,
        p.message_to_seller AS shopee_message,
        jsonb_strip_nulls(jsonb_build_object(
            'username', p.buyer_username,
            'marketplace_order_id', p.marketplace_order_id,
            'contact_marketplace_id', p.contact_marketplace_id
        )) AS informacoes_comprador,
        p.situacao_pedido_id,
        pb.bling_id
    FROM public.pedidos AS p
    INNER JOIN public.canais_venda AS cv ON cv.id = p.canal_venda_id
    LEFT JOIN public.pedidos_bling AS pb ON pb.numero_pedido = p.numero_pedido
    WHERE cv.slug = 'shopee'
      AND p.situacao_pedido_id = 2
      AND EXISTS (
          SELECT 1 FROM public.itens_pedido AS ip
           WHERE ip.pedido_id = p.id AND ip.personalizado = true
      )
),
latest_logs AS (
    SELECT DISTINCT ON (l.order_sn) l.order_sn, l.executed_at, l.status
      FROM public.logs_execucao_ia AS l
     ORDER BY l.order_sn, l.executed_at DESC, l.id DESC
),
chat_stats AS (
    SELECT bo.id AS pedido_id,
           max(vm.created_at) AS last_chat_message_at,
           max(vm.created_at) FILTER (WHERE vm.from_user_name = bo.buyer_username) AS last_buyer_message_at
      FROM base_orders AS bo
      LEFT JOIN public.view_mensagens_chat_ai AS vm
        ON bo.buyer_username IS NOT NULL AND bo.buyer_username <> ''
       AND (vm.from_user_name = bo.buyer_username OR vm.to_user_name = bo.buyer_username)
     GROUP BY bo.id
),
item_personalizations AS (
    SELECT ip.pedido_id,
           jsonb_agg(
               jsonb_build_object(
                   'id', ip.id,
                   'codigo', ip.sku_externo,
                   'descricao', ip.descricao,
                   'quantidade', ip.quantidade,
                   'valor', ip.preco_unitario,
                   'unidade', 'UN',
                   'personalizado', ip.personalizado,
                   'produto', jsonb_build_object('id', ip.produto_id),
                   'personalizations', COALESCE((
                       SELECT jsonb_agg(
                           jsonb_build_object(
                               'id', pp.id,
                               'item_pedido_id', pp.item_pedido_id,
                               'item_id', pp.item_id,
                               'item_description', pp.item_description,
                               'quantity_to_personalize', COALESCE(
                                   NULLIF(pp.detalhes_personalizacao ->> 'quantity_to_personalize', '')::integer,
                                   NULLIF(pp.metadata ->> 'quantity_to_personalize', '')::integer,
                                   1
                               ),
                               'customization_name', pp.customization_name,
                               'name_source_message_id', pp.name_source_message_id,
                               'customization_initial', pp.customization_initial,
                               'initial_source_message_id', COALESCE(
                                   pp.detalhes_personalizacao ->> 'initial_source_message_id',
                                   pp.metadata ->> 'initial_source_message_id'
                               ),
                               'status', pp.status,
                               'reasoning', pp.reasoning
                           ) ORDER BY pp.id
                       )
                         FROM public.personalizacoes_pedido AS pp
                        WHERE pp.item_pedido_id = ip.id
                           OR (pp.item_pedido_id IS NULL
                               AND pp.shopee_order_sn = (
                                   SELECT p2.codigo_pedido_externo
                                     FROM public.pedidos AS p2
                                    WHERE p2.id = ip.pedido_id
                               )
                               AND pp.item_description = ip.descricao)
                   ), '[]'::jsonb)
               ) ORDER BY ip.id
           ) AS itens
      FROM base_orders AS bo
      INNER JOIN public.itens_pedido AS ip
        ON ip.pedido_id = bo.id AND ip.personalizado = true
     GROUP BY ip.pedido_id
)
SELECT bo.id,
       bo.numero_pedido,
       bo.numero_loja,
       bo.data_pedido,
       bo.contato,
       bo.nome_cliente,
       bo.bling_id,
       true AS personalizado,
       false AS deletado,
       bo.informacoes_comprador,
       COALESCE(bo.shopee_message, '') AS shopee_message,
       bo.buyer_username,
       COALESCE(cs.last_chat_message_at IS NOT NULL, false) AS has_chat_messages,
       COALESCE(NULLIF(trim(COALESCE(bo.shopee_message, '')), '') IS NOT NULL
                OR cs.last_buyer_message_at IS NOT NULL, false) AS has_buyer_message,
       cs.last_chat_message_at,
       cs.last_buyer_message_at,
       ll.executed_at AS last_ai_executed_at,
       COALESCE(ll.status, 'NOT_PROCESSED') AS ai_status,
       CASE
           WHEN NOT COALESCE(NULLIF(trim(COALESCE(bo.shopee_message, '')), '') IS NOT NULL
                             OR cs.last_buyer_message_at IS NOT NULL, false) THEN false
           WHEN ll.executed_at IS NULL THEN true
           WHEN COALESCE(ll.status, '') IN ('error', 'db_error', 'no_response') THEN true
           WHEN cs.last_buyer_message_at IS NOT NULL
                AND cs.last_buyer_message_at > ll.executed_at THEN true
           ELSE false
       END AS needs_ai_processing,
       COALESCE(ip.itens, '[]'::jsonb) AS itens
  FROM base_orders AS bo
  LEFT JOIN chat_stats AS cs ON cs.pedido_id = bo.id
  LEFT JOIN latest_logs AS ll ON ll.order_sn = bo.numero_loja
  LEFT JOIN item_personalizations AS ip ON ip.pedido_id = bo.id;

GRANT SELECT ON public.view_pedidos_personalizados_ai TO service_role;
