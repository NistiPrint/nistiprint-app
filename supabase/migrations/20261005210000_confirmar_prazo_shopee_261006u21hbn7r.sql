-- O operador confirmou na tela da Shopee que este pedido deve ser postado ate
-- 06/10/2026. Registra o prazo oficial e preserva o valor estimado anterior.
DO $$
DECLARE
    v_pedido_id integer;
    prazo_anterior timestamptz;
BEGIN
    SELECT p.id, p.data_limite_envio
      INTO v_pedido_id, prazo_anterior
      FROM public.pedidos p
     WHERE p.marketplace_module_id = 'shopee'
       AND p.marketplace_order_id = '261006U21HBN7R'
       AND p.situacao_pedido_id = 2
     FOR UPDATE;

    IF v_pedido_id IS NULL OR prazo_anterior = '2026-10-06T23:59:59-03:00'::timestamptz THEN
        RETURN;
    END IF;

    UPDATE public.pedido_snapshots s
       SET logistics = s.logistics || jsonb_build_object(
           'deadline', '2026-10-06T23:59:59-03:00',
           'dispatch_deadline_source', 'shopee.seller_panel.confirmed',
           'deadline_estimated', false,
           'deadline_reconciliation', COALESCE(s.logistics->'deadline_reconciliation', '{}'::jsonb)
               || jsonb_build_object(
                   'previous_deadline', prazo_anterior,
                   'confirmed_at', now(),
                   'evidence', 'Operador confirmou na tela da Shopee: prazo de envio em 06/10/2026'
               )
       ), updated_at = now()
     WHERE s.pedido_id = v_pedido_id;

    UPDATE public.pedidos
       SET data_limite_envio = '2026-10-06T23:59:59-03:00',
           prazo_postagem_tentativas = 0,
           prazo_postagem_proxima_tentativa = NULL,
           prazo_postagem_motivo = NULL
     WHERE id = v_pedido_id;
END;
$$;
