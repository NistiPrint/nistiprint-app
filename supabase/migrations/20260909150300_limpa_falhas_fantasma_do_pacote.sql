-- Linhas de fila que continuaram 'failed' com o texto do 23505 embora o pedido
-- ja tenha referencia de ERP. Sao itens duplicados do mesmo pedido: a
-- recuperacao (20260909150200) reabriu um por pedido, o outro ficou para tras
-- com a mensagem antiga. Deixa-los em 'failed' faz a fila de falhas mentir
-- sobre o que esta realmente parado.
UPDATE public.pending_order_reconciliations t
   SET status = 'skipped_duplicate',
       last_error = 'Irmao de pacote; referencia ERP aplicada no pedido',
       erp_order_id = NULL,
       resolved_at = COALESCE(t.resolved_at, now()),
       updated_at = now()
  FROM public.pedidos p
 WHERE p.id = t.pedido_id
   AND t.status = 'failed'
   AND t.last_error LIKE '%ux_pending_order_reconciliation%'
   AND p.erp_order_id IS NOT NULL;
