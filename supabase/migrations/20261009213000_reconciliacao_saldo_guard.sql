-- JIT decisions are made in the worker, so the database must validate the
-- exact stock/reservation snapshot under deterministic row locks before any
-- movement is written. A stale decision rolls back and is retried from fresh
-- stock. Intermediate stock may not go negative; only raw materials may.
CREATE OR REPLACE FUNCTION public.reconciliar_item_estoque(
    p_item_id integer,
    p_demanda_id integer,
    p_movimentos jsonb,
    p_snapshot jsonb,
    p_correlation_id uuid,
    p_user_id character varying
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_movimento jsonb;
    v_produto_id integer;
    v_deposito_id integer;
    v_quantidade numeric;
    v_tipo_movimentacao varchar(50);
    v_tipo_produto text;
    v_saldo_antes numeric;
    v_saldo_depois numeric;
    v_reservado numeric;
    v_reserva_propria numeric;
    v_disponivel numeric;
    v_mov_id integer;
    v_produto_nome varchar(255);
    v_demanda_nome varchar(255);
    v_usuario_id integer;
    v_estagio varchar(50);
    v_movimentos_resp jsonb := '[]'::jsonb;
BEGIN
    IF jsonb_typeof(p_movimentos) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_movimentos) = 0 THEN
        RAISE EXCEPTION 'A reconciliação requer uma lista de movimentos não vazia'
            USING ERRCODE = '22023';
    END IF;

    IF p_user_id IS NOT NULL AND p_user_id ~ '^-?\d+$' THEN
        BEGIN
            v_usuario_id := p_user_id::integer;
        EXCEPTION WHEN OTHERS THEN
            v_usuario_id := NULL;
        END;
    ELSE
        v_usuario_id := NULL;
    END IF;

    SELECT descricao INTO v_demanda_nome
      FROM public.demandas_producao WHERE id = p_demanda_id;

    -- Create missing balances in one deterministic order, then lock all rows
    -- in that same order before validating any worker-side stock decision.
    FOR v_produto_id, v_deposito_id IN
        SELECT DISTINCT (m.value->>'produto_id')::integer,
                        (m.value->>'deposito_id')::integer
          FROM jsonb_array_elements(p_movimentos) AS m(value)
         ORDER BY 1, 2
    LOOP
        IF v_produto_id IS NULL OR v_deposito_id IS NULL THEN
            RAISE EXCEPTION 'Produto e depósito são obrigatórios em cada movimento'
                USING ERRCODE = '22023';
        END IF;
        INSERT INTO public.estoque_atual(produto_id, deposito_id, saldo_atual)
        VALUES (v_produto_id, v_deposito_id, 0)
        ON CONFLICT (produto_id, deposito_id) DO NOTHING;
    END LOOP;

    PERFORM 1
      FROM public.estoque_atual s
      JOIN (
          SELECT DISTINCT (m.value->>'produto_id')::integer AS produto_id,
                          (m.value->>'deposito_id')::integer AS deposito_id
            FROM jsonb_array_elements(p_movimentos) AS m(value)
      ) keys USING (produto_id, deposito_id)
     ORDER BY s.produto_id, s.deposito_id
     FOR UPDATE OF s;

    -- Every intermediate-consumption decision must carry the exact physical
    -- balance, reservation total, own remaining reservation and available
    -- amount that the worker used to choose stock vs. JIT production.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(p_movimentos) m(value)
         WHERE upper(coalesce(m.value->>'tipo', '')) = 'CONS_INT'
           AND NOT (m.value ? 'expected_saldo')
    ) THEN
        RAISE EXCEPTION 'CONS_INT sem fotografia de saldo; recalcule a reconciliação'
            USING ERRCODE = '22023';
    END IF;

    FOR v_movimento IN
        SELECT value FROM jsonb_array_elements(p_movimentos)
         WHERE value ? 'expected_saldo'
    LOOP
        v_produto_id := (v_movimento->>'produto_id')::integer;
        v_deposito_id := (v_movimento->>'deposito_id')::integer;
        SELECT saldo_atual, coalesce(reservado, 0), coalesce(disponivel, saldo_atual)
          INTO v_saldo_antes, v_reservado, v_disponivel
          FROM public.estoque_atual
         WHERE produto_id = v_produto_id AND deposito_id = v_deposito_id;

        SELECT coalesce(sum(greatest(
                   0,
                   coalesce(quantidade_alocada, 0)
                   - coalesce(quantidade_consumida, 0)
                   - coalesce(quantidade_liberada, 0)
               )), 0)
          INTO v_reserva_propria
          FROM public.demanda_alocacoes_estoque
         WHERE item_id = p_item_id::text
           AND produto_id = v_produto_id::text
           AND deposito_id = v_deposito_id
           AND status = 'PENDENTE';

        IF v_saldo_antes IS DISTINCT FROM (v_movimento->>'expected_saldo')::numeric
           OR v_reservado IS DISTINCT FROM (v_movimento->>'expected_reservado')::numeric
           OR v_reserva_propria IS DISTINCT FROM (v_movimento->>'expected_reserva_propria')::numeric
           OR (v_disponivel + v_reserva_propria)
                IS DISTINCT FROM (v_movimento->>'expected_disponivel')::numeric THEN
            RAISE EXCEPTION 'Fotografia de estoque/reserva desatualizada para produto % depósito %',
                v_produto_id, v_deposito_id USING ERRCODE = '40001';
        END IF;
    END LOOP;

    FOR v_movimento IN SELECT value FROM jsonb_array_elements(p_movimentos)
    LOOP
        v_produto_id := nullif(v_movimento->>'produto_id', '')::integer;
        v_deposito_id := nullif(v_movimento->>'deposito_id', '')::integer;
        v_quantidade := nullif(v_movimento->>'quantidade', '')::numeric;
        v_tipo_movimentacao := nullif(trim(v_movimento->>'tipo'), '');
        v_estagio := v_movimento->>'estagio';
        IF v_produto_id IS NULL OR v_deposito_id IS NULL OR v_quantidade IS NULL
           OR v_tipo_movimentacao IS NULL OR v_quantidade = 0 THEN
            RAISE EXCEPTION 'Movimento inválido na reconciliação'
                USING ERRCODE = '22023';
        END IF;

        SELECT nome, tipo_produto INTO v_produto_nome, v_tipo_produto
          FROM public.produtos WHERE id = v_produto_id;
        SELECT saldo_atual INTO v_saldo_antes
          FROM public.estoque_atual
         WHERE produto_id = v_produto_id AND deposito_id = v_deposito_id;
        v_saldo_depois := v_saldo_antes + v_quantidade;

        IF v_saldo_depois < 0 AND upper(coalesce(v_tipo_produto, '')) <> 'MATERIA_PRIMA' THEN
            RAISE EXCEPTION 'Saldo negativo proibido para produto intermediário/acabado %', v_produto_id
                USING ERRCODE = '23514';
        END IF;
        IF upper(v_tipo_movimentacao) = 'CONS_INT' AND v_saldo_depois < 0 THEN
            RAISE EXCEPTION 'CONS_INT não pode consumir saldo inexistente do produto %', v_produto_id
                USING ERRCODE = '23514';
        END IF;

        UPDATE public.estoque_atual
           SET saldo_atual = v_saldo_depois,
               ultima_atualizacao = now(), updated_at = now()
         WHERE produto_id = v_produto_id AND deposito_id = v_deposito_id;

        INSERT INTO public.movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            documento_referencia, correlation_id, origem_tipo, data_movimentacao,
            item_demanda_id, produto_nome, demanda_nome, estagio
        ) VALUES (
            v_produto_id, v_deposito_id, v_tipo_movimentacao, v_quantidade,
            v_saldo_antes, v_saldo_depois, v_movimento->>'motivo', v_usuario_id,
            CASE WHEN v_usuario_id IS NULL THEN 'caller=' || coalesce(p_user_id, 'NULL') ELSE NULL END,
            p_correlation_id, NULL, now(), p_item_id, v_produto_nome, v_demanda_nome, v_estagio
        ) RETURNING id INTO v_mov_id;

        IF p_item_id IS NOT NULL AND p_demanda_id IS NOT NULL THEN
            INSERT INTO public.demanda_estoque_processado (
                item_id, demanda_id, estagio, quantidade, correlation_id,
                saldo_acumulado, produto_id, tipo_movimentacao, created_at
            ) VALUES (
                p_item_id, p_demanda_id, v_estagio, v_quantidade,
                p_correlation_id, v_saldo_depois, v_produto_id, v_tipo_movimentacao, now()
            )
            ON CONFLICT (item_id, estagio, correlation_id, produto_id, tipo_movimentacao)
                WHERE correlation_id IS NOT NULL
            DO UPDATE SET quantidade = demanda_estoque_processado.quantidade + EXCLUDED.quantidade,
                          saldo_acumulado = EXCLUDED.saldo_acumulado,
                          updated_at = now();
        END IF;

        v_movimentos_resp := v_movimentos_resp || jsonb_build_array(jsonb_build_object(
            'movimento_id', v_mov_id, 'produto_id', v_produto_id,
            'deposito_id', v_deposito_id, 'quantidade', v_quantidade,
            'tipo', v_tipo_movimentacao, 'estagio', v_estagio
        ));
    END LOOP;

    RETURN jsonb_build_object(
        'sucesso', true, 'movimentos', v_movimentos_resp, 'erros', '[]'::jsonb,
        'snapshot_id', NULL, 'item_id', p_item_id, 'demanda_id', p_demanda_id,
        'correlation_id', p_correlation_id
    );
EXCEPTION WHEN OTHERS THEN
    RETURN jsonb_build_object(
        'sucesso', false, 'erro', SQLERRM, 'sqlstate', SQLSTATE,
        'item_id', p_item_id, 'demanda_id', p_demanda_id,
        'correlation_id', p_correlation_id
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.reconciliar_item_estoque(integer, integer, jsonb, jsonb, uuid, character varying)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reconciliar_item_estoque(integer, integer, jsonb, jsonb, uuid, character varying)
    TO service_role;
