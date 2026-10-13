-- Preserve collection history and link new delivery rows to their operation.
ALTER TABLE public.entrega_producao
    ADD COLUMN IF NOT EXISTS operation_id uuid;

ALTER TABLE public.entrega_producao
    DROP CONSTRAINT IF EXISTS entrega_producao_demanda_id_fkey,
    DROP CONSTRAINT IF EXISTS entrega_producao_item_demanda_id_fkey;

ALTER TABLE public.entrega_producao
    ADD CONSTRAINT entrega_producao_demanda_id_fkey
        FOREIGN KEY (demanda_id) REFERENCES public.demandas_producao(id) ON DELETE RESTRICT,
    ADD CONSTRAINT entrega_producao_item_demanda_id_fkey
        FOREIGN KEY (item_demanda_id) REFERENCES public.itens_demanda(id) ON DELETE RESTRICT,
    ADD CONSTRAINT entrega_producao_operation_id_fkey
        FOREIGN KEY (operation_id) REFERENCES public.estoque_operacoes(operation_id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_entrega_producao_operation_id
    ON public.entrega_producao(operation_id) WHERE operation_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.registrar_coleta_demanda_transacional(
    p_operation_id uuid,p_content_hash text,p_demanda_id integer,p_quantidade integer,
    p_user_id text,p_finalizar_total boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_hash text; v_state text; v_result jsonb; v_status text;
        v_total numeric; v_collected numeric; v_remaining numeric; v_take integer;
        v_next numeric; v_demand public.demandas_producao%ROWTYPE; v_exit jsonb;
BEGIN
    IF p_operation_id IS NULL OR p_demanda_id IS NULL OR p_content_hash !~ '^[0-9a-f]{64}$'
       OR (NOT coalesce(p_finalizar_total,false) AND coalesce(p_quantidade,0)<=0) THEN
        RAISE EXCEPTION 'Contrato de coleta inválido' USING ERRCODE='22023';
    END IF;
    INSERT INTO public.estoque_operacoes(operation_id,command_type,content_hash,source)
    VALUES(p_operation_id,'COLETA_DEMANDA',p_content_hash,
        jsonb_build_object('demanda_id',p_demanda_id,'finalizar_total',coalesce(p_finalizar_total,false)))
    ON CONFLICT(operation_id) DO NOTHING;
    SELECT content_hash,status,result INTO v_hash,v_state,v_result
      FROM public.estoque_operacoes WHERE operation_id=p_operation_id FOR UPDATE;
    IF v_hash IS DISTINCT FROM p_content_hash THEN
        RAISE EXCEPTION 'operation_id reutilizado com conteúdo diferente' USING ERRCODE='23505';
    END IF;
    IF v_state='CONFIRMADO' THEN RETURN v_result; END IF;
    SELECT * INTO v_demand FROM public.demandas_producao WHERE id=p_demanda_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Demanda não encontrada' USING ERRCODE='P0002'; END IF;
    SELECT coalesce(sum(quantidade),0) INTO v_total FROM public.itens_demanda WHERE demanda_id=p_demanda_id;
    SELECT coalesce(sum(quantidade),0) INTO v_collected FROM public.entrega_producao WHERE demanda_id=p_demanda_id;
    v_remaining:=greatest(0,v_total-v_collected);
    IF v_remaining<>trunc(v_remaining) THEN
        RAISE EXCEPTION 'Saldo coletável fracionário exige revisão da demanda' USING ERRCODE='23514';
    END IF;
    v_take:=CASE WHEN coalesce(p_finalizar_total,false) THEN v_remaining::integer ELSE p_quantidade END;
    IF NOT coalesce(p_finalizar_total,false) AND v_demand.status='COLETADO' THEN
        RAISE EXCEPTION 'Demanda já foi totalmente coletada' USING ERRCODE='23514';
    END IF;
    IF v_take<0 OR v_take>v_remaining THEN
        RAISE EXCEPTION 'Quantidade a coletar excede o saldo restante' USING ERRCODE='23514';
    END IF;
    IF v_take>0 THEN
        INSERT INTO public.entrega_producao(
            id,item_demanda_id,data_entrega,quantidade,demanda_id,user_id,created_at,operation_id
        ) VALUES(p_operation_id::text,NULL,current_date,v_take,p_demanda_id,p_user_id,now(),p_operation_id);
    END IF;
    v_next:=v_collected+v_take;
    v_status:=CASE WHEN v_next>=v_total THEN 'COLETADO'
                   WHEN v_next>0 THEN 'COLETA_PARCIAL'
                   WHEN EXISTS (SELECT 1 FROM public.itens_demanda i WHERE i.demanda_id=p_demanda_id
                                AND coalesce(i.status_item,'Pendente')<>'Pendente') THEN 'EM_PRODUCAO'
                   ELSE 'AGUARDANDO' END;
    UPDATE public.demandas_producao SET status=v_status,
        data_conclusao=CASE WHEN v_status='COLETADO' THEN coalesce(data_conclusao,now()) ELSE data_conclusao END,
        horario_coleta=CASE WHEN v_status='COLETADO'
            THEN (now() AT TIME ZONE 'America/Sao_Paulo')::time ELSE horario_coleta END,
        updated_at=now() WHERE id=p_demanda_id RETURNING * INTO v_demand;
    IF v_status='COLETADO' THEN
        v_exit:=public.registrar_saida_coleta_demanda(p_demanda_id,coalesce(p_user_id,'System'));
        IF coalesce((v_exit->>'ok')::boolean,false) IS NOT TRUE THEN
            RAISE EXCEPTION 'Baixa final da coleta falhou: %',v_exit USING ERRCODE='23514';
        END IF;
        IF nullif(v_exit->>'correlation_id','') IS NOT NULL THEN
            UPDATE public.movimentacoes_estoque SET operation_id=p_operation_id
             WHERE correlation_id=(v_exit->>'correlation_id')::uuid AND operation_id IS NULL;
        END IF;
    END IF;
    v_result:=jsonb_build_object('operation_id',p_operation_id,'status','CONFIRMADO',
        'demanda',to_jsonb(v_demand),'quantidade_coletada',v_take,
        'quantidade_total_coletada',v_next,'saida_estoque',v_exit,'confirmed_at',now());
    UPDATE public.estoque_operacoes SET status='CONFIRMADO',result=v_result,confirmed_at=now()
     WHERE operation_id=p_operation_id;
    RETURN v_result;
END; $$;

REVOKE ALL ON FUNCTION public.registrar_coleta_demanda_transacional(uuid,text,integer,integer,text,boolean)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_coleta_demanda_transacional(uuid,text,integer,integer,text,boolean)
    TO service_role;

NOTIFY pgrst, 'reload schema';
