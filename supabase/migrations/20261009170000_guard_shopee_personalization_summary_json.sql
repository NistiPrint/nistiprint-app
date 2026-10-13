-- Keep summary counts working when legacy item JSON is null or has an unexpected shape.
CREATE OR REPLACE VIEW public.view_shopee_personalization_order_summary
WITH (security_invoker = true) AS
SELECT v.id, p.marketplace_integration_id, v.numero_pedido, v.numero_loja,
       v.nome_cliente, v.buyer_username, v.data_pedido, v.has_chat_messages,
       v.needs_ai_processing, v.ai_status,
       EXISTS (
         SELECT 1
           FROM jsonb_array_elements(
             CASE WHEN jsonb_typeof(v.itens) = 'array' THEN v.itens ELSE '[]'::jsonb END
           ) AS item(value)
         CROSS JOIN LATERAL jsonb_array_elements(
             CASE WHEN jsonb_typeof(item.value->'personalizations') = 'array'
                  THEN item.value->'personalizations' ELSE '[]'::jsonb END
         ) AS personalization(value)
         WHERE NULLIF(trim(COALESCE(personalization.value->>'customization_name',
                                    personalization.value->>'customization_initial', '')), '') IS NOT NULL
       ) AS has_identified_name,
       (upper(COALESCE(v.ai_status, '')) = 'NO_PERSONALIZATION_FOUND' OR EXISTS (
         SELECT 1
           FROM jsonb_array_elements(
             CASE WHEN jsonb_typeof(v.itens) = 'array' THEN v.itens ELSE '[]'::jsonb END
           ) AS item(value)
         CROSS JOIN LATERAL jsonb_array_elements(
             CASE WHEN jsonb_typeof(item.value->'personalizations') = 'array'
                  THEN item.value->'personalizations' ELSE '[]'::jsonb END
         ) AS personalization(value)
         WHERE upper(COALESCE(personalization.value->>'status', '')) = 'NO_PERSONALIZATION_FOUND'
            OR (upper(COALESCE(personalization.value->>'status', '')) = 'SUCCESS'
                AND NULLIF(trim(COALESCE(personalization.value->>'customization_name',
                                         personalization.value->>'customization_initial', '')), '') IS NULL)
       )) AS has_no_name
  FROM public.view_vendas_personalizadas_v3 v
  JOIN public.pedidos p ON p.id = v.id;

REVOKE ALL ON public.view_shopee_personalization_order_summary FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.view_shopee_personalization_order_summary TO service_role;
