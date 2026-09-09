-- Reparo dos pedidos que a fila desistiu de reconciliar.
--
-- 106 itens (101 'failed', 5 'pending') travaram no 23505 entre 04/08 e hoje.
-- Os 106 sao irmaos de pacote de um pedido que ja aplicou a referencia — nao
-- eram pedidos ausentes do Bling, eram pedidos cuja referencia estava a uma
-- linha de distancia. Enquanto ficam sem `erp_order_id` nao sao faturaveis nem
-- imprimiveis.
--
-- Com `pack_id` preenchido (20260909150000) e a guarda restaurada
-- (20260909150100), reaplicar a referencia via a propria RPC e suficiente:
-- ela grava pedido, snapshot, refs e encerra a fila pelo mesmo caminho do fluxo
-- normal. Nada de UPDATE a mao replicando a logica.

DO $$
DECLARE
  r RECORD;
  v_total INT := 0;
BEGIN
  FOR r IN
    SELECT DISTINCT ON (t.pedido_id)
           t.id AS fila_id,
           p.id AS pedido_id,
           p.marketplace_order_id,
           irmao.erp_integration_id,
           irmao.erp_store_id,
           irmao.erp_order_id,
           irmao.erp_order_number
      FROM public.pending_order_reconciliations t
      JOIN public.pedidos p ON p.id = t.pedido_id
      JOIN LATERAL (
        SELECT s.erp_integration_id, s.erp_store_id,
               s.erp_order_id, s.erp_order_number
          FROM public.pedidos s
         WHERE s.pack_id = p.pack_id
           AND s.id <> p.id
           AND s.erp_order_id IS NOT NULL
         ORDER BY s.id
         LIMIT 1
      ) irmao ON TRUE
     WHERE t.status IN ('pending', 'failed')
       AND p.pack_id IS NOT NULL
       AND p.erp_order_id IS NULL
     ORDER BY t.pedido_id, (t.status = 'pending') DESC, t.id
  LOOP
    -- Reabre o item so quando ele e o unico da fila daquele pedido: o indice
    -- ux_pending_order_reconciliation_order admite um 'pending' por pedido.
    IF NOT EXISTS (
      SELECT 1 FROM public.pending_order_reconciliations o
       WHERE o.pedido_id = r.pedido_id
         AND o.status = 'pending'
         AND o.id <> r.fila_id
    ) THEN
      UPDATE public.pending_order_reconciliations
         SET status = 'pending', last_error = NULL,
             next_attempt_after = NULL, updated_at = now()
       WHERE id = r.fila_id;
    END IF;

    PERFORM public.enrich_order_erp_reference(
      r.pedido_id,
      r.erp_integration_id,
      r.erp_store_id,
      r.erp_order_id,
      r.erp_order_number,
      r.marketplace_order_id
    );
    v_total := v_total + 1;
  END LOOP;

  RAISE NOTICE 'Irmaos de pacote recuperados: %', v_total;
END $$;
