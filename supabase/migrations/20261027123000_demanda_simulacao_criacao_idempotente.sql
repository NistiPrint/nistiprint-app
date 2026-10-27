-- Repetir um POST de criação com o mesmo operation_id devolve o mesmo cenário.
CREATE OR REPLACE FUNCTION public.demanda_simulacao_criar(
    p_pedido_ids integer[], p_fingerprint text, p_snapshot jsonb, p_state jsonb, p_actor text
) RETURNS public.demanda_simulacoes
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    v_row public.demanda_simulacoes%ROWTYPE;
    v_operation_id uuid;
    v_hash text;
    v_existing record;
BEGIN
    IF p_pedido_ids IS NULL OR cardinality(p_pedido_ids) = 0
       OR cardinality(p_pedido_ids) <> (SELECT count(DISTINCT u.pedido_id) FROM unnest(p_pedido_ids) AS u(pedido_id))
       OR p_snapshot IS NULL OR p_state IS NULL
       OR jsonb_typeof(p_snapshot) <> 'object' OR jsonb_typeof(p_state) <> 'object'
       OR p_fingerprint IS NULL THEN
        RAISE EXCEPTION 'SIMULACAO_INVALIDA' USING ERRCODE = '22023';
    END IF;
    v_operation_id := NULLIF(p_snapshot->>'operation_id', '')::uuid;
    v_hash := NULLIF(p_snapshot->>'request_hash', '');
    IF v_operation_id IS NULL OR v_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'SIMULACAO_INVALIDA' USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(v_operation_id::text, 0));
    SELECT simulacao_id, request_hash INTO v_existing
      FROM public.demanda_simulacao_eventos WHERE operation_id = v_operation_id;
    IF FOUND THEN
        IF v_existing.request_hash <> v_hash THEN
            RAISE EXCEPTION 'SIMULACAO_OPERACAO_REUTILIZADA' USING ERRCODE = '23505';
        END IF;
        SELECT * INTO v_row FROM public.demanda_simulacoes WHERE id = v_existing.simulacao_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'SIMULACAO_NAO_ENCONTRADA' USING ERRCODE = 'P0002'; END IF;
        RETURN v_row;
    END IF;
    PERFORM 1 FROM public.pedidos WHERE id = ANY(p_pedido_ids) ORDER BY id FOR SHARE;
    IF (SELECT count(DISTINCT id) FROM public.vw_pedidos_pendentes_despacho
        WHERE id = ANY(p_pedido_ids)) <> cardinality(p_pedido_ids)
       OR public.demanda_simulacao_fingerprint(p_pedido_ids) <> p_fingerprint THEN
        RAISE EXCEPTION 'SIMULACAO_ORIGEM_ALTERADA' USING ERRCODE = '40001';
    END IF;
    INSERT INTO public.demanda_simulacoes(pedido_ids, snapshot, state, created_by)
    VALUES(p_pedido_ids, p_snapshot, p_state, p_actor) RETURNING * INTO v_row;
    INSERT INTO public.demanda_simulacao_eventos
      (simulacao_id, operation_id, request_hash, action, actor, details)
    VALUES(v_row.id, v_operation_id, v_hash, 'criar', p_actor,
           jsonb_build_object('total_pedidos', cardinality(p_pedido_ids)));
    RETURN v_row;
END;
$$;
