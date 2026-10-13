CREATE OR REPLACE FUNCTION public.substituir_previsao_consumo_demanda(
    p_demanda_id integer,
    p_linhas jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=public,pg_temp
AS $$
DECLARE
    v_count integer;
BEGIN
    IF p_demanda_id IS NULL OR jsonb_typeof(p_linhas) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Previsão inválida' USING ERRCODE='22023';
    END IF;

    PERFORM 1 FROM public.demandas_producao WHERE id=p_demanda_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Demanda % não encontrada', p_demanda_id USING ERRCODE='23503';
    END IF;

    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_linhas) AS item(value)
        WHERE nullif(item.value->>'produto_id','') IS NULL
           OR nullif(item.value->>'quantidade_prevista','') IS NULL
           OR (item.value->>'quantidade_prevista')::numeric <= 0
    ) THEN
        RAISE EXCEPTION 'Previsão contém produto ou quantidade inválida' USING ERRCODE='22023';
    END IF;

    DELETE FROM public.previsao_consumo_demanda
     WHERE demanda_id=p_demanda_id AND status='PLANEJADO';

    INSERT INTO public.previsao_consumo_demanda(
        demanda_id, produto_id, quantidade_prevista, unidade, status
    )
    SELECT p_demanda_id, (linha->>'produto_id')::bigint,
           (linha->>'quantidade_prevista')::numeric,
           nullif(linha->>'unidade',''), 'PLANEJADO'
      FROM jsonb_array_elements(p_linhas) AS item(value);
    GET DIAGNOSTICS v_count=ROW_COUNT;

    RETURN jsonb_build_object('status','CONFIRMADO','demanda_id',p_demanda_id,'linhas',v_count);
END;
$$;

REVOKE ALL ON FUNCTION public.substituir_previsao_consumo_demanda(integer,jsonb)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.substituir_previsao_consumo_demanda(integer,jsonb)
    TO service_role;
