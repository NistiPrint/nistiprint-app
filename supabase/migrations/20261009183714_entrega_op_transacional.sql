-- Consumo proporcional, entrada do acabado, checkpoint e reservas na mesma transação.
CREATE OR REPLACE FUNCTION public.entregar_ordem_producao_transacional(
    p_operation_id uuid,p_content_hash text,p_ordem_id integer,p_deposito_id integer,
    p_quantidade numeric,p_actor_id integer
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_op public.ordens_producao%ROWTYPE; v_hash text; v_state text; v_result jsonb;
        v_total numeric; v_done numeric; v_component record; v_alloc record;
        v_take numeric; v_remaining numeric; v_piece numeric; v_before numeric; v_after numeric;
        v_deposito integer; v_deposito_min integer; v_deposito_max integer;
        v_move_id integer; v_snapshot jsonb := '[]'::jsonb; v_now numeric;
BEGIN
    IF p_operation_id IS NULL OR p_ordem_id IS NULL OR p_deposito_id IS NULL
       OR p_content_hash !~ '^[0-9a-f]{64}$' OR p_quantidade IS NULL OR p_quantidade<=0 THEN
        RAISE EXCEPTION 'Contrato de entrega de OP inválido' USING ERRCODE='22023';
    END IF;
    INSERT INTO public.estoque_operacoes(operation_id,command_type,content_hash,source,actor_id)
    VALUES(p_operation_id,'OP_DELIVERY',p_content_hash,
        jsonb_build_object('ordem_producao_id',p_ordem_id,'quantidade',p_quantidade),p_actor_id)
    ON CONFLICT(operation_id) DO NOTHING;
    SELECT content_hash,status,result INTO v_hash,v_state,v_result
      FROM public.estoque_operacoes WHERE operation_id=p_operation_id FOR UPDATE;
    IF v_hash IS DISTINCT FROM p_content_hash THEN
        RAISE EXCEPTION 'operation_id reutilizado com conteúdo diferente' USING ERRCODE='23505';
    END IF;
    IF v_state='CONFIRMADO' THEN RETURN jsonb_set(v_result,'{replayed}','true'::jsonb,true); END IF;
    SELECT * INTO v_op FROM public.ordens_producao WHERE id=p_ordem_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'OP não encontrada' USING ERRCODE='P0002'; END IF;
    IF v_op.status NOT IN ('PENDING','IN_PROGRESS','PARTIALLY_DELIVERED') THEN
        RAISE EXCEPTION 'Apenas OP ativa pode receber entrega' USING ERRCODE='23514';
    END IF;
    SELECT min(deposito_id),max(deposito_id) INTO v_deposito_min,v_deposito_max
      FROM public.demanda_alocacoes_estoque
     WHERE item_id='OP/'||p_ordem_id::text AND processo_origem='ORDEM_PRODUCAO';
    IF v_deposito_min IS NOT NULL AND v_deposito_min IS DISTINCT FROM v_deposito_max THEN
        RAISE EXCEPTION 'Reservas da OP estão em depósitos diferentes' USING ERRCODE='23514';
    END IF;
    v_deposito:=coalesce(v_deposito_min,p_deposito_id);
    v_total := coalesce(v_op.quantidade,0);
    v_done := greatest(coalesce(v_op.quantidade_produzida,0),
                       coalesce(nullif(v_op.dados_adicionais->>'quantidade_produzida','')::numeric,0));
    IF v_total<=0 OR v_done+p_quantidade>v_total THEN
        RAISE EXCEPTION 'Quantidade entregue excede o saldo planejado' USING ERRCODE='23514';
    END IF;
    INSERT INTO public.estoque_atual(produto_id,deposito_id,saldo_atual)
    VALUES(v_op.produto_id,v_deposito,0) ON CONFLICT(produto_id,deposito_id) DO NOTHING;
    PERFORM 1 FROM public.estoque_atual s
     WHERE s.deposito_id=v_deposito AND s.produto_id IN (
        SELECT componente_id FROM public.componentes_ordem_producao WHERE ordem_producao_id=p_ordem_id
        UNION SELECT v_op.produto_id
     ) ORDER BY s.produto_id,s.deposito_id FOR UPDATE;

    FOR v_component IN SELECT id,componente_id,quantidade_necessaria,quantidade_utilizada
        FROM public.componentes_ordem_producao WHERE ordem_producao_id=p_ordem_id
        ORDER BY componente_id,id FOR UPDATE
    LOOP
        v_take := coalesce(v_component.quantidade_necessaria,0)*p_quantidade/v_total;
        v_remaining := v_take;
        IF v_take<0 THEN RAISE EXCEPTION 'Necessidade de componente inválida' USING ERRCODE='22023'; END IF;
        FOR v_alloc IN SELECT id,quantidade_alocada,quantidade_consumida,quantidade_liberada
            FROM public.demanda_alocacoes_estoque
            WHERE item_id='OP/'||p_ordem_id::text AND produto_id=v_component.componente_id::text
              AND deposito_id=v_deposito AND processo_origem='ORDEM_PRODUCAO' AND status='PENDENTE'
              AND quantidade_alocada>quantidade_consumida+quantidade_liberada
            ORDER BY created_at,id FOR UPDATE
        LOOP
            EXIT WHEN v_remaining<=0;
            v_piece:=least(v_remaining,v_alloc.quantidade_alocada-v_alloc.quantidade_consumida-v_alloc.quantidade_liberada);
            UPDATE public.estoque_atual SET saldo_atual=saldo_atual-v_piece,reservado=coalesce(reservado,0)-v_piece,
                updated_at=now(),ultima_atualizacao=now()
             WHERE produto_id=v_component.componente_id AND deposito_id=v_deposito
               AND coalesce(reservado,0)>=v_piece
             RETURNING saldo_atual+v_piece,saldo_atual INTO v_before,v_after;
            IF NOT FOUND THEN RAISE EXCEPTION 'Reserva insuficiente para OP % / produto %',p_ordem_id,v_component.componente_id USING ERRCODE='23514'; END IF;
            INSERT INTO public.movimentacoes_estoque(
                produto_id,deposito_id,tipo_movimentacao,quantidade,saldo_antes,saldo_depois,
                motivo,usuario_id,documento_referencia,correlation_id,operation_id,data_movimentacao
            ) VALUES(v_component.componente_id,v_deposito,'SAIDA_INSUMO_PRODUCAO',-v_piece,
                v_before,v_after,'Consumo proporcional da OP '||p_ordem_id,p_actor_id,p_ordem_id::text,
                p_operation_id,p_operation_id,now()) RETURNING id INTO v_move_id;
            UPDATE public.demanda_alocacoes_estoque SET quantidade_consumida=quantidade_consumida+v_piece,
                status=CASE WHEN quantidade_consumida+v_piece+quantidade_liberada>=quantidade_alocada
                            THEN 'PROCESSADA' ELSE 'PENDENTE' END,
                processed_at=CASE WHEN quantidade_consumida+v_piece+quantidade_liberada>=quantidade_alocada
                                  THEN now() ELSE processed_at END,
                movimento_id=v_move_id,operation_id=p_operation_id
             WHERE id=v_alloc.id;
            v_snapshot:=v_snapshot||jsonb_build_array(jsonb_build_object(
                'produto_id',v_component.componente_id,'quantidade_consumida',v_piece,
                'saldo_antes',v_before,'saldo_depois',v_after));
            v_remaining:=v_remaining-v_piece;
        END LOOP;
        IF v_remaining>0 THEN RAISE EXCEPTION 'Reserva vinculada ausente para OP % / produto %',p_ordem_id,v_component.componente_id USING ERRCODE='23514'; END IF;
        UPDATE public.componentes_ordem_producao SET quantidade_utilizada=coalesce(quantidade_utilizada,0)+v_take,
            updated_at=now() WHERE id=v_component.id;
    END LOOP;

    UPDATE public.estoque_atual SET saldo_atual=saldo_atual+p_quantidade,
        updated_at=now(),ultima_atualizacao=now()
     WHERE produto_id=v_op.produto_id AND deposito_id=v_deposito
     RETURNING saldo_atual-p_quantidade,saldo_atual INTO v_before,v_after;
    INSERT INTO public.movimentacoes_estoque(
        produto_id,deposito_id,tipo_movimentacao,quantidade,saldo_antes,saldo_depois,
        motivo,usuario_id,documento_referencia,correlation_id,operation_id,data_movimentacao
    ) VALUES(v_op.produto_id,v_deposito,'ENTRADA',p_quantidade,v_before,v_after,
        'Entrada da OP '||p_ordem_id,p_actor_id,p_ordem_id::text,p_operation_id,p_operation_id,now())
    RETURNING id INTO v_move_id;
    v_done:=v_done+p_quantidade;
    UPDATE public.ordens_producao SET quantidade_produzida=v_done,
        dados_adicionais=coalesce(dados_adicionais,'{}'::jsonb)||jsonb_build_object('quantidade_produzida',v_done),
        status=CASE WHEN v_done>=v_total THEN 'COMPLETED' ELSE 'PARTIALLY_DELIVERED' END,
        data_fim=CASE WHEN v_done>=v_total THEN current_date ELSE data_fim END,updated_at=now()
     WHERE id=p_ordem_id RETURNING * INTO v_op;
    v_result:=jsonb_build_object('operation_id',p_operation_id,'status','CONFIRMADO','replayed',false,
        'ordem_producao',to_jsonb(v_op),'snapshot_componentes',v_snapshot,
        'movimento_produto_final_id',v_move_id,'confirmed_at',now());
    UPDATE public.estoque_operacoes SET status='CONFIRMADO',result=v_result,confirmed_at=now()
     WHERE operation_id=p_operation_id;
    RETURN v_result;
END; $$;

REVOKE ALL ON FUNCTION public.entregar_ordem_producao_transacional(uuid,text,integer,integer,numeric,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.entregar_ordem_producao_transacional(uuid,text,integer,integer,numeric,integer) TO service_role;
