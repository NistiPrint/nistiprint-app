-- Calculate the same future window once per logistics mode and marketplace account.
-- The pending-order set is much larger than the number of distinct schedules.
CREATE OR REPLACE FUNCTION public.despacho_recalcular_compromissos()
RETURNS integer
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_qtd integer;
BEGIN
    WITH chaves AS MATERIALIZED (
        SELECT DISTINCT p.modalidade_logistica_id, p.marketplace_integration_id
          FROM public.pedidos p
          JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
         WHERE p.despachado_em IS NULL
           AND p.situacao_pedido_id IN (2, 3, 4)
           AND m.tipo_prazo = 'FIXO'
    ), janelas AS MATERIALIZED (
        SELECT c.modalidade_logistica_id, c.marketplace_integration_id, j.corte_em
          FROM chaves c
          CROSS JOIN LATERAL public.proxima_janela_logistica(
              c.modalidade_logistica_id, c.marketplace_integration_id, now()
          ) j
    ), alvo AS (
        SELECT p.id, j.corte_em
          FROM janelas j
          JOIN public.pedidos p
            ON p.modalidade_logistica_id = j.modalidade_logistica_id
           AND p.marketplace_integration_id IS NOT DISTINCT FROM j.marketplace_integration_id
         WHERE p.despachado_em IS NULL
           AND p.situacao_pedido_id IN (2, 3, 4)
           AND p.compromisso_logistico_em IS DISTINCT FROM j.corte_em
    )
    UPDATE public.pedidos p
       SET compromisso_logistico_em = a.corte_em
      FROM alvo a
     WHERE p.id = a.id;

    GET DIAGNOSTICS v_qtd = ROW_COUNT;
    RETURN v_qtd;
END;
$fn$;

-- The Bling ingest resolves orders by both account and store order number.
CREATE INDEX IF NOT EXISTS idx_pedidos_bling_integration_numero_loja
    ON public.pedidos_bling (bling_integration_id, numero_loja)
    WHERE numero_loja IS NOT NULL;

-- The ingest health check counts invalid signatures in a recent time window.
CREATE INDEX IF NOT EXISTS ix_webhook_events_signature_status_checked_at
    ON public.webhook_events (signature_status, signature_checked_at);
