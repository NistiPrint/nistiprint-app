-- Aggregate the Shopee personalized order counters from relational sources.
-- This avoids evaluating the nested item/chat JSON views five times per page.
CREATE OR REPLACE FUNCTION public.contar_pedidos_personalizados_shopee(
    p_integration_id integer DEFAULT NULL,
    p_include_unassigned boolean DEFAULT false
)
RETURNS TABLE(
    pendente_ia bigint,
    com_chat bigint,
    sem_chat bigint,
    nome_identificado bigint,
    sem_nome bigint
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO public, pg_temp AS $$
WITH pedidos_base AS MATERIALIZED (
    SELECT p.id, p.marketplace_integration_id, p.codigo_pedido_externo,
           p.buyer_username
      FROM public.pedidos p
      JOIN public.canais_venda cv ON cv.id = p.canal_venda_id AND cv.slug = 'shopee'
     WHERE p.situacao_pedido_id IN (2, 3, 4)
       AND (p_integration_id IS NULL
            OR p.marketplace_integration_id = p_integration_id
            OR (p_include_unassigned AND p.marketplace_integration_id IS NULL))
       AND EXISTS (
           SELECT 1 FROM public.itens_pedido ip
            WHERE ip.pedido_id = p.id AND ip.personalizado = true
       )
), personalizacao AS MATERIALIZED (
    SELECT b.id AS pedido_id,
           bool_or(NULLIF(trim(COALESCE(pp.customization_name, pp.customization_initial, '')), '') IS NOT NULL) AS tem_nome,
           bool_or(upper(COALESCE(pp.status, '')) = 'NO_PERSONALIZATION_FOUND'
                   OR (upper(COALESCE(pp.status, '')) = 'SUCCESS'
                       AND NULLIF(trim(COALESCE(pp.customization_name, pp.customization_initial, '')), '') IS NULL)) AS sem_nome
      FROM pedidos_base b
      JOIN public.itens_pedido ip ON ip.pedido_id = b.id AND ip.personalizado = true
      LEFT JOIN public.personalizacoes_pedido pp
        ON pp.item_pedido_id = ip.id
        OR (pp.item_pedido_id IS NULL
            AND pp.shopee_order_sn = b.codigo_pedido_externo
            AND pp.item_description = ip.descricao)
     GROUP BY b.id
), chat AS MATERIALIZED (
    SELECT b.id AS pedido_id,
           bool_or(vm.created_at IS NOT NULL) AS tem_chat
      FROM pedidos_base b
      LEFT JOIN public.view_mensagens_chat_ai vm
        ON b.buyer_username IS NOT NULL AND b.buyer_username <> ''
       AND (vm.from_user_name = b.buyer_username OR vm.to_user_name = b.buyer_username)
     GROUP BY b.id
)
SELECT count(*) FILTER (WHERE v.needs_ai_processing),
       count(*) FILTER (WHERE COALESCE(c.tem_chat, false) OR v.has_buyer_message),
       count(*) FILTER (WHERE NOT (COALESCE(c.tem_chat, false) OR v.has_buyer_message)),
       count(*) FILTER (WHERE COALESCE(p.tem_nome, false)),
       count(*) FILTER (WHERE COALESCE(p.sem_nome, false))
  FROM pedidos_base b
  JOIN public.view_pedidos_personalizados_ai v ON v.id = b.id
  LEFT JOIN personalizacao p ON p.pedido_id = b.id
  LEFT JOIN chat c ON c.pedido_id = b.id;
$$;

REVOKE ALL ON FUNCTION public.contar_pedidos_personalizados_shopee(integer,boolean)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.contar_pedidos_personalizados_shopee(integer,boolean)
    TO service_role;
