-- Início e cancelamento de OP vinculam estoque, reserva e status na mesma transação.
CREATE OR REPLACE FUNCTION public.iniciar_ordem_producao_transacional(
    p_operation_id uuid, p_content_hash text, p_ordem_id integer,
    p_deposito_id integer, p_bom_version_id uuid, p_actor_id integer,
    p_needs jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_op public.ordens_producao%ROWTYPE; v_hash text; v_state text; v_result jsonb;
        v_need jsonb; v_product integer; v_qty numeric; v_allocations jsonb := '[]'::jsonb;
BEGIN
    IF p_operation_id IS NULL OR p_ordem_id IS NULL OR p_deposito_id IS NULL
       OR p_bom_version_id IS NULL OR p_content_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_needs) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Contrato de início de OP inválido' USING ERRCODE='22023';
    END IF;
    INSERT INTO public.estoque_operacoes(operation_id,command_type,content_hash,source,actor_id)
    VALUES(p_operation_id,'OP_START',p_content_hash,jsonb_build_object('ordem_producao_id',p_ordem_id),p_actor_id)
    ON CONFLICT(operation_id) DO NOTHING;
    SELECT content_hash,status,result INTO v_hash,v_state,v_result
      FROM public.estoque_operacoes WHERE operation_id=p_operation_id FOR UPDATE;
    IF v_hash IS DISTINCT FROM p_content_hash THEN
        RAISE EXCEPTION 'operation_id reutilizado com conteúdo diferente' USING ERRCODE='23505';
    END IF;
    IF v_state='CONFIRMADO' THEN RETURN v_result; END IF;
    SELECT * INTO v_op FROM public.ordens_producao WHERE id=p_ordem_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'OP não encontrada' USING ERRCODE='P0002'; END IF;
    IF v_op.status <> 'DRAFT' THEN RAISE EXCEPTION 'Apenas OP DRAFT pode iniciar' USING ERRCODE='23514'; END IF;
    IF EXISTS (SELECT 1 FROM public.componentes_ordem_producao WHERE ordem_producao_id=p_ordem_id) THEN
        RAISE EXCEPTION 'OP DRAFT já possui componentes; exige revisão antes de iniciar' USING ERRCODE='23514';
    END IF;
    FOR v_product,v_qty IN
        SELECT (value->>'componente_id')::integer, sum((value->>'quantidade_necessaria')::numeric)
          FROM jsonb_array_elements(p_needs) GROUP BY 1 ORDER BY 1
    LOOP
        IF v_product IS NULL OR v_qty IS NULL OR v_qty <= 0 THEN
            RAISE EXCEPTION 'Necessidade de componente inválida' USING ERRCODE='22023';
        END IF;
        INSERT INTO public.estoque_atual(produto_id,deposito_id,saldo_atual)
        VALUES(v_product,p_deposito_id,0) ON CONFLICT(produto_id,deposito_id) DO NOTHING;
    END LOOP;
    PERFORM 1 FROM public.estoque_atual s
     WHERE s.deposito_id=p_deposito_id
       AND s.produto_id IN (SELECT DISTINCT (value->>'componente_id')::integer FROM jsonb_array_elements(p_needs))
     ORDER BY s.produto_id,s.deposito_id FOR UPDATE;
    FOR v_need IN SELECT value FROM jsonb_array_elements(p_needs) ORDER BY (value->>'componente_id')::integer
    LOOP
        v_product := (v_need->>'componente_id')::integer;
        v_qty := (v_need->>'quantidade_necessaria')::numeric;
        UPDATE public.estoque_atual SET reservado=coalesce(reservado,0)+v_qty,
            updated_at=now(),ultima_atualizacao=now()
         WHERE produto_id=v_product AND deposito_id=p_deposito_id;
        INSERT INTO public.componentes_ordem_producao(
            ordem_producao_id,componente_id,sku,descricao,quantidade_necessaria,quantidade_utilizada,status
        ) VALUES(p_ordem_id,v_product,v_need->>'sku',v_need->>'descricao',v_qty,0,'PENDENTE');
        INSERT INTO public.demanda_alocacoes_estoque(
            demanda_id,item_id,produto_id,correlation_id,quantidade_alocada,tipo_alocacao,
            processo_origem,status,metadata,deposito_id,operation_id
        ) VALUES('OP/'||p_ordem_id::text,'OP/'||p_ordem_id::text,v_product::text,p_operation_id::text,
            v_qty,'ORDEM_PRODUCAO','ORDEM_PRODUCAO','PENDENTE',
            jsonb_build_object('ordem_producao_id',p_ordem_id,'bom_version_id',p_bom_version_id),
            p_deposito_id,p_operation_id);
        v_allocations := v_allocations || jsonb_build_array(jsonb_build_object(
            'produto_id',v_product,'quantidade_reservada',v_qty,'deposito_id',p_deposito_id));
    END LOOP;
    UPDATE public.ordens_producao SET status='PENDING',data_inicio=current_date,
        bom_version_id=p_bom_version_id,updated_at=now() WHERE id=p_ordem_id RETURNING * INTO v_op;
    v_result := jsonb_build_object('operation_id',p_operation_id,'status','CONFIRMADO',
        'ordem_producao',to_jsonb(v_op),'reservas',v_allocations,'confirmed_at',now());
    UPDATE public.estoque_operacoes SET status='CONFIRMADO',result=v_result,confirmed_at=now()
     WHERE operation_id=p_operation_id;
    RETURN v_result;
END; $$;

CREATE OR REPLACE FUNCTION public.cancelar_ordem_producao_transacional(
    p_operation_id uuid,p_content_hash text,p_ordem_id integer,p_actor_id integer
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_op public.ordens_producao%ROWTYPE; v_hash text; v_state text; v_result jsonb;
        v_alloc record; v_remaining numeric;
BEGIN
    IF p_operation_id IS NULL OR p_ordem_id IS NULL OR p_content_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Contrato de cancelamento de OP inválido' USING ERRCODE='22023';
    END IF;
    INSERT INTO public.estoque_operacoes(operation_id,command_type,content_hash,source,actor_id)
    VALUES(p_operation_id,'OP_CANCEL',p_content_hash,jsonb_build_object('ordem_producao_id',p_ordem_id),p_actor_id)
    ON CONFLICT(operation_id) DO NOTHING;
    SELECT content_hash,status,result INTO v_hash,v_state,v_result
      FROM public.estoque_operacoes WHERE operation_id=p_operation_id FOR UPDATE;
    IF v_hash IS DISTINCT FROM p_content_hash THEN
        RAISE EXCEPTION 'operation_id reutilizado com conteúdo diferente' USING ERRCODE='23505';
    END IF;
    IF v_state='CONFIRMADO' THEN RETURN v_result; END IF;
    SELECT * INTO v_op FROM public.ordens_producao WHERE id=p_ordem_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'OP não encontrada' USING ERRCODE='P0002'; END IF;
    IF v_op.status IN ('COMPLETED','CANCELED') THEN RAISE EXCEPTION 'OP já finalizada ou cancelada' USING ERRCODE='23514'; END IF;
    FOR v_alloc IN SELECT id,produto_id,deposito_id,quantidade_alocada,quantidade_consumida,quantidade_liberada
        FROM public.demanda_alocacoes_estoque
        WHERE item_id='OP/'||p_ordem_id::text AND processo_origem='ORDEM_PRODUCAO' AND status='PENDENTE'
        ORDER BY produto_id,deposito_id,created_at,id FOR UPDATE
    LOOP
        v_remaining := v_alloc.quantidade_alocada-v_alloc.quantidade_consumida-v_alloc.quantidade_liberada;
        IF v_remaining <= 0 THEN CONTINUE; END IF;
        UPDATE public.estoque_atual SET reservado=coalesce(reservado,0)-v_remaining,
            updated_at=now(),ultima_atualizacao=now()
         WHERE produto_id::text=v_alloc.produto_id AND deposito_id=v_alloc.deposito_id
           AND coalesce(reservado,0)>=v_remaining;
        IF NOT FOUND THEN RAISE EXCEPTION 'Reserva insuficiente para liberar OP % / produto %',p_ordem_id,v_alloc.produto_id USING ERRCODE='23514'; END IF;
        UPDATE public.demanda_alocacoes_estoque SET quantidade_liberada=quantidade_liberada+v_remaining,
            status='CANCELADA',cancelled_at=now()
         WHERE id=v_alloc.id;
    END LOOP;
    UPDATE public.ordens_producao SET status='CANCELED',updated_at=now()
     WHERE id=p_ordem_id RETURNING * INTO v_op;
    v_result:=jsonb_build_object('operation_id',p_operation_id,'status','CONFIRMADO',
        'ordem_producao',to_jsonb(v_op),'confirmed_at',now());
    UPDATE public.estoque_operacoes SET status='CONFIRMADO',result=v_result,confirmed_at=now()
     WHERE operation_id=p_operation_id;
    RETURN v_result;
END; $$;

REVOKE ALL ON FUNCTION public.iniciar_ordem_producao_transacional(uuid,text,integer,integer,uuid,integer,jsonb) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.cancelar_ordem_producao_transacional(uuid,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.iniciar_ordem_producao_transacional(uuid,text,integer,integer,uuid,integer,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.cancelar_ordem_producao_transacional(uuid,text,integer,integer) TO service_role;
