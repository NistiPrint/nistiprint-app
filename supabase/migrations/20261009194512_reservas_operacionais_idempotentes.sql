CREATE TABLE IF NOT EXISTS public.estoque_reservas_operacionais (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    operation_id uuid NOT NULL UNIQUE REFERENCES public.estoque_operacoes(operation_id) ON DELETE RESTRICT,
    origem_tipo text NOT NULL,
    origem_id text NOT NULL,
    produto_id integer NOT NULL REFERENCES public.produtos(id) ON DELETE RESTRICT,
    deposito_id integer NOT NULL REFERENCES public.depositos(id) ON DELETE RESTRICT,
    quantidade numeric(15,4) NOT NULL CHECK (quantidade > 0),
    quantidade_consumida numeric(15,4) NOT NULL DEFAULT 0 CHECK (quantidade_consumida >= 0),
    quantidade_liberada numeric(15,4) NOT NULL DEFAULT 0 CHECK (quantidade_liberada >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (quantidade_consumida + quantidade_liberada <= quantidade)
);

CREATE INDEX IF NOT EXISTS ix_estoque_reservas_operacionais_origem
    ON public.estoque_reservas_operacionais(origem_tipo, origem_id, produto_id, deposito_id, created_at);

CREATE OR REPLACE FUNCTION public.executar_comando_reserva_estoque(
    p_operation_id uuid,
    p_content_hash text,
    p_action text,
    p_source jsonb,
    p_actor_id integer,
    p_produto_id integer,
    p_deposito_id integer,
    p_quantidade numeric,
    p_motivo text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_hash text;
    v_status text;
    v_result jsonb;
    v_source_type text := nullif(trim(p_source->>'source_type'), '');
    v_source_id text := nullif(trim(p_source->>'source_id'), '');
    v_stock public.estoque_atual%ROWTYPE;
    v_reserva public.estoque_reservas_operacionais%ROWTYPE;
    v_remaining numeric(15,4);
    v_available numeric(15,4);
    v_take numeric(15,4);
    v_done numeric(15,4) := 0;
    v_movement_id integer;
    v_after numeric(15,4);
BEGIN
    IF p_operation_id IS NULL OR p_content_hash !~ '^[0-9a-f]{64}$'
       OR p_action NOT IN ('RESERVAR', 'LIBERAR', 'CONSUMIR')
       OR v_source_type IS NULL OR v_source_id IS NULL
       OR p_produto_id IS NULL OR p_deposito_id IS NULL
       OR (p_action = 'RESERVAR' AND (p_quantidade IS NULL OR p_quantidade <= 0))
       OR (p_action = 'CONSUMIR' AND (p_quantidade IS NULL OR p_quantidade <= 0))
       OR (p_action <> 'RESERVAR' AND p_quantidade IS NOT NULL AND p_quantidade <= 0)
       OR (p_quantidade IS NOT NULL AND p_quantidade <> round(p_quantidade, 4)) THEN
        RAISE EXCEPTION 'Contrato de reserva de estoque inválido' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.estoque_operacoes(operation_id, command_type, content_hash, source, actor_id)
    VALUES (p_operation_id, p_action || '_RESERVA', p_content_hash, coalesce(p_source, '{}'::jsonb), p_actor_id)
    ON CONFLICT (operation_id) DO NOTHING;
    SELECT content_hash, status, result INTO v_hash, v_status, v_result
      FROM public.estoque_operacoes WHERE operation_id = p_operation_id FOR UPDATE;
    IF v_hash IS DISTINCT FROM p_content_hash THEN
        RAISE EXCEPTION 'operation_id de reserva reutilizado com outro conteúdo' USING ERRCODE = '23505';
    END IF;
    IF v_status = 'CONFIRMADO' THEN RETURN v_result; END IF;

    INSERT INTO public.estoque_atual(produto_id, deposito_id, saldo_atual, reservado)
    VALUES (p_produto_id, p_deposito_id, 0, 0)
    ON CONFLICT (produto_id, deposito_id) DO NOTHING;
    SELECT * INTO v_stock FROM public.estoque_atual
     WHERE produto_id = p_produto_id AND deposito_id = p_deposito_id FOR UPDATE;

    IF p_action = 'RESERVAR' THEN
        UPDATE public.estoque_atual
           SET reservado = coalesce(reservado, 0) + p_quantidade,
               updated_at = now(), ultima_atualizacao = now()
         WHERE produto_id = p_produto_id AND deposito_id = p_deposito_id;
        INSERT INTO public.estoque_reservas_operacionais(
            operation_id, origem_tipo, origem_id, produto_id, deposito_id, quantidade
        ) VALUES (
            p_operation_id, v_source_type, v_source_id, p_produto_id, p_deposito_id, p_quantidade
        );
        v_done := p_quantidade;
    ELSE
        SELECT coalesce(sum(quantidade - quantidade_consumida - quantidade_liberada), 0)
          INTO v_available
          FROM public.estoque_reservas_operacionais
         WHERE origem_tipo = v_source_type AND origem_id = v_source_id
           AND produto_id = p_produto_id AND deposito_id = p_deposito_id
           AND quantidade > quantidade_consumida + quantidade_liberada;
        v_remaining := coalesce(p_quantidade, v_available);
        IF p_action = 'CONSUMIR' AND v_available < p_quantidade THEN
            RAISE EXCEPTION 'Reserva insuficiente para consumo: disponível %, solicitado %', v_available, p_quantidade
                USING ERRCODE = '23514';
        END IF;
        FOR v_reserva IN
            SELECT * FROM public.estoque_reservas_operacionais
             WHERE origem_tipo = v_source_type AND origem_id = v_source_id
               AND produto_id = p_produto_id AND deposito_id = p_deposito_id
               AND quantidade > quantidade_consumida + quantidade_liberada
             ORDER BY created_at, id FOR UPDATE
        LOOP
            EXIT WHEN v_remaining <= 0;
            v_take := least(v_remaining,
                v_reserva.quantidade - v_reserva.quantidade_consumida - v_reserva.quantidade_liberada);
            IF p_action = 'CONSUMIR' THEN
                UPDATE public.estoque_reservas_operacionais
                   SET quantidade_consumida = quantidade_consumida + v_take, updated_at = now()
                 WHERE id = v_reserva.id;
            ELSE
                UPDATE public.estoque_reservas_operacionais
                   SET quantidade_liberada = quantidade_liberada + v_take, updated_at = now()
                 WHERE id = v_reserva.id;
            END IF;
            v_remaining := v_remaining - v_take;
            v_done := v_done + v_take;
        END LOOP;

        IF v_done > coalesce(v_stock.reservado, 0) THEN
            RAISE EXCEPTION 'Saldo reservado inconsistente: reservado %, operação %', v_stock.reservado, v_done
                USING ERRCODE = '23514';
        END IF;
        v_after := v_stock.saldo_atual;
        IF p_action = 'CONSUMIR' THEN
            v_after := coalesce(v_stock.saldo_atual, 0) - v_done;
            UPDATE public.estoque_atual
               SET saldo_atual = v_after, reservado = coalesce(reservado, 0) - v_done,
                   updated_at = now(), ultima_atualizacao = now()
             WHERE produto_id = p_produto_id AND deposito_id = p_deposito_id;
            INSERT INTO public.movimentacoes_estoque(
                produto_id, deposito_id, tipo_movimentacao, quantidade, saldo_antes,
                saldo_depois, motivo, usuario_id, documento_referencia, correlation_id,
                operation_id, data_movimentacao
            ) VALUES (
                p_produto_id, p_deposito_id, 'SAIDA_RESERVADA', -v_done,
                v_stock.saldo_atual, v_after, p_motivo, p_actor_id,
                v_source_type || ':' || v_source_id, p_operation_id,
                p_operation_id, now()
            ) RETURNING id INTO v_movement_id;
        ELSE
            UPDATE public.estoque_atual
               SET reservado = coalesce(reservado, 0) - v_done,
                   updated_at = now(), ultima_atualizacao = now()
             WHERE produto_id = p_produto_id AND deposito_id = p_deposito_id;
        END IF;
    END IF;

    v_result := jsonb_build_object(
        'operation_id', p_operation_id, 'status', 'CONFIRMADO', 'action', p_action,
        'source_type', v_source_type, 'source_id', v_source_id,
        'produto_id', p_produto_id, 'deposito_id', p_deposito_id,
        'quantidade', v_done, 'movimento_id', v_movement_id,
        'saldo_atual', CASE WHEN p_action = 'CONSUMIR' THEN v_after ELSE v_stock.saldo_atual END,
        'confirmado_em', now()
    );
    UPDATE public.estoque_operacoes SET status = 'CONFIRMADO', result = v_result, confirmed_at = now()
     WHERE operation_id = p_operation_id;
    RETURN v_result;
END;
$function$;

REVOKE ALL ON FUNCTION public.executar_comando_reserva_estoque(uuid, text, text, jsonb, integer, integer, integer, numeric, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.executar_comando_reserva_estoque(uuid, text, text, jsonb, integer, integer, integer, numeric, text)
    TO service_role;
