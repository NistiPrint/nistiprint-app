-- A reduction changes the effective production intent. Until an operator-facing
-- compensating command exists, reject it before visual counters can diverge
-- from confirmed stock movements.
CREATE OR REPLACE FUNCTION public.validar_progresso_item_monotonico()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
    v_field text;
    v_new numeric;
    v_old numeric;
BEGIN
    FOREACH v_field IN ARRAY ARRAY[
        'capas_impressas_qtd', 'capas_produzidas_qtd',
        'capas_prontas_retirada_qtd', 'miolos_prontos_retirada_qtd',
        'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd',
        'finalizados_qtd'
    ] LOOP
        v_new := coalesce(nullif(to_jsonb(NEW)->>v_field, '')::numeric, 0);
        v_old := coalesce(nullif(to_jsonb(OLD)->>v_field, '')::numeric, 0);
        IF v_new < 0 OR v_new > NEW.quantidade THEN
            RAISE EXCEPTION 'Progresso % fora do intervalo 0..quantidade (%)', v_field, NEW.quantidade
                USING ERRCODE = '22023';
        END IF;
        IF v_new < v_old THEN
            RAISE EXCEPTION 'RECONCILIACAO_REDUCAO_REQUER_COMPENSACAO:%', v_field
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS trg_itens_demanda_progresso_monotonico ON public.itens_demanda;
CREATE TRIGGER trg_itens_demanda_progresso_monotonico
BEFORE UPDATE OF capas_impressas_qtd, capas_produzidas_qtd,
    capas_prontas_retirada_qtd, miolos_prontos_retirada_qtd,
    expedicao_capas_retiradas_qtd, expedicao_miolos_retirados_qtd,
    finalizados_qtd
ON public.itens_demanda
FOR EACH ROW EXECUTE FUNCTION public.validar_progresso_item_monotonico();

REVOKE ALL ON FUNCTION public.validar_progresso_item_monotonico() FROM PUBLIC, anon, authenticated;
