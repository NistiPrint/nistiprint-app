-- O operador confirmou na tela da Shopee que estes pedidos devem ser postados
-- ate 06/10/2026. Registra os prazos oficiais e preserva as estimativas antigas.
DO $$
DECLARE
    alvo record;
BEGIN
    FOR alvo IN
        SELECT p.id, p.marketplace_order_id, p.data_limite_envio AS prazo_anterior
          FROM public.pedidos p
         WHERE p.marketplace_module_id = 'shopee'
           AND p.marketplace_order_id = ANY(ARRAY['261006U3CJEY1X', '261006U4YAJ3GC'])
           AND p.situacao_pedido_id = 2
           AND p.data_limite_envio IS DISTINCT FROM '2026-10-06T23:59:59-03:00'::timestamptz
           AND NOT EXISTS (
               SELECT 1 FROM public.pedidos_shopee so
                WHERE so.codigo_pedido = p.marketplace_order_id
                  AND so.ship_by_date IS NOT NULL
           )
         FOR UPDATE OF p
    LOOP
        UPDATE public.pedido_snapshots s
           SET logistics = s.logistics || jsonb_build_object(
               'deadline', '2026-10-06T23:59:59-03:00',
               'dispatch_deadline_source', 'shopee.seller_panel.confirmed',
               'deadline_estimated', false,
               'deadline_reconciliation', COALESCE(s.logistics->'deadline_reconciliation', '{}'::jsonb)
                   || jsonb_build_object(
                       'previous_deadline', alvo.prazo_anterior,
                       'confirmed_at', now(),
                       'evidence', 'Operador confirmou na tela da Shopee: prazo de envio em 06/10/2026'
                   )
           ), updated_at = now()
         WHERE s.pedido_id = alvo.id;

        UPDATE public.pedidos
           SET data_limite_envio = '2026-10-06T23:59:59-03:00',
               prazo_postagem_tentativas = 0,
               prazo_postagem_proxima_tentativa = NULL,
               prazo_postagem_motivo = NULL
         WHERE id = alvo.id;
    END LOOP;
END;
$$;
