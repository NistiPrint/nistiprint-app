CREATE OR REPLACE FUNCTION public.liberar_reserva_item_estoque(
    p_operation_id uuid, p_content_hash text, p_source jsonb, p_actor_id integer,
    p_item_id integer, p_quantidade numeric, p_motivo text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_hash text;
    v_status text;
    v_result jsonb;
    v_allocation record;
    v_remaining numeric := p_quantidade;
    v_take numeric;
    v_released numeric := 0;
BEGIN
    IF p_operation_id IS NULL OR p_content_hash !~ '^[0-9a-f]{64}$'
       OR p_item_id IS NULL OR p_quantidade IS NULL OR p_quantidade <= 0 THEN
        RAISE EXCEPTION 'Contrato de liberação inválido' USING ERRCODE = '22023';
    END IF;
    INSERT INTO public.estoque_operacoes(operation_id, command_type, content_hash, source, actor_id)
    VALUES (p_operation_id, 'LIBERACAO_RESERVA', p_content_hash, coalesce(p_source, '{}'::jsonb), p_actor_id)
    ON CONFLICT (operation_id) DO NOTHING;
    SELECT content_hash, status, result INTO v_hash, v_status, v_result
      FROM public.estoque_operacoes WHERE operation_id = p_operation_id FOR UPDATE;
    IF v_hash IS DISTINCT FROM p_content_hash THEN
        RAISE EXCEPTION 'operation_id de liberação reutilizado com outro conteúdo' USING ERRCODE = '23505';
    END IF;
    IF v_status = 'CONFIRMADO' THEN RETURN v_result; END IF;

    FOR v_allocation IN
        SELECT id, produto_id, deposito_id, quantidade_alocada, quantidade_consumida, quantidade_liberada
          FROM public.demanda_alocacoes_estoque
         WHERE item_id = p_item_id::text AND status = 'PENDENTE'
           AND quantidade_alocada > quantidade_consumida + quantidade_liberada
         ORDER BY created_at, id FOR UPDATE
    LOOP
        EXIT WHEN v_remaining <= 0;
        v_take := least(v_remaining,
            v_allocation.quantidade_alocada - v_allocation.quantidade_consumida - v_allocation.quantidade_liberada);
        UPDATE public.estoque_atual
           SET reservado = coalesce(reservado, 0) - v_take,
               updated_at = now(), ultima_atualizacao = now()
         WHERE produto_id = v_allocation.produto_id::integer
           AND deposito_id = v_allocation.deposito_id
           AND coalesce(reservado, 0) >= v_take;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Saldo reservado inconsistente para alocação %', v_allocation.id
                USING ERRCODE = '23514';
        END IF;
        UPDATE public.demanda_alocacoes_estoque
           SET quantidade_liberada = quantidade_liberada + v_take,
               status = CASE WHEN quantidade_consumida + quantidade_liberada + v_take >= quantidade_alocada
                             THEN 'CANCELADA' ELSE 'PENDENTE' END,
               cancelled_at = CASE WHEN quantidade_consumida + quantidade_liberada + v_take >= quantidade_alocada
                                   THEN now() ELSE cancelled_at END,
               metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
                   'ultima_liberacao', p_motivo, 'operation_id', p_operation_id)
         WHERE id = v_allocation.id;
        v_remaining := v_remaining - v_take;
        v_released := v_released + v_take;
    END LOOP;
    v_result := jsonb_build_object('operation_id', p_operation_id, 'status', 'CONFIRMADO',
                                   'item_id', p_item_id, 'quantidade_liberada', v_released,
                                   'quantidade_nao_alocada', v_remaining, 'confirmed_at', now());
    UPDATE public.estoque_operacoes SET status = 'CONFIRMADO', result = v_result, confirmed_at = now()
     WHERE operation_id = p_operation_id;
    RETURN v_result;
END;
$function$;

REVOKE ALL ON FUNCTION public.liberar_reserva_item_estoque(uuid, text, jsonb, integer, integer, numeric, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.liberar_reserva_item_estoque(uuid, text, jsonb, integer, integer, numeric, text)
    TO service_role;
