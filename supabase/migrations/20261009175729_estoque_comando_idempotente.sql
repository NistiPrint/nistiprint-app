-- Comandos físicos de estoque com identidade estável e resultado recuperável.
-- Migration aditiva: não migra nem reinterpreta movimentos históricos.

CREATE TABLE IF NOT EXISTS public.estoque_operacoes (
    operation_id uuid PRIMARY KEY,
    command_type text NOT NULL,
    content_hash text NOT NULL,
    source jsonb NOT NULL DEFAULT '{}'::jsonb,
    actor_id integer,
    status text NOT NULL DEFAULT 'PROCESSANDO'
        CHECK (status IN ('PROCESSANDO', 'CONFIRMADO')),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    confirmed_at timestamptz,
    CONSTRAINT estoque_operacoes_confirmed_result_check
        CHECK ((status = 'CONFIRMADO') = (result IS NOT NULL AND confirmed_at IS NOT NULL))
);

ALTER TABLE public.estoque_operacoes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.estoque_operacoes FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.estoque_operacoes TO service_role;

ALTER TABLE public.movimentacoes_estoque
    ADD COLUMN IF NOT EXISTS operation_id uuid;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'movimentacoes_estoque_operation_id_fkey'
           AND conrelid = 'public.movimentacoes_estoque'::regclass
    ) THEN
        ALTER TABLE public.movimentacoes_estoque
            ADD CONSTRAINT movimentacoes_estoque_operation_id_fkey
            FOREIGN KEY (operation_id) REFERENCES public.estoque_operacoes(operation_id)
            ON DELETE RESTRICT;
    END IF;
END;
$migration$;

CREATE INDEX IF NOT EXISTS idx_movimentacoes_estoque_operation_id
    ON public.movimentacoes_estoque(operation_id)
    WHERE operation_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.executar_comando_estoque(
    p_operation_id uuid,
    p_command_type text,
    p_content_hash text,
    p_source jsonb,
    p_actor_id integer,
    p_movimentos jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_hash text;
    v_status text;
    v_result jsonb;
    v_move jsonb;
    v_product_id integer;
    v_deposit_id integer;
    v_type text;
    v_quantity numeric(15,4);
    v_before numeric(15,4);
    v_after numeric(15,4);
    v_move_id integer;
    v_movements jsonb := '[]'::jsonb;
    v_balances jsonb := '[]'::jsonb;
BEGIN
    IF p_operation_id IS NULL OR nullif(trim(p_command_type), '') IS NULL
       OR nullif(trim(p_content_hash), '') IS NULL
       OR jsonb_typeof(p_movimentos) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_movimentos) = 0 THEN
        RAISE EXCEPTION 'Contrato de comando de estoque inválido' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.estoque_operacoes (
        operation_id, command_type, content_hash, source, actor_id
    ) VALUES (
        p_operation_id, p_command_type, p_content_hash,
        coalesce(p_source, '{}'::jsonb), p_actor_id
    ) ON CONFLICT (operation_id) DO NOTHING;

    SELECT content_hash, status, result
      INTO v_hash, v_status, v_result
      FROM public.estoque_operacoes
     WHERE operation_id = p_operation_id
     FOR UPDATE;

    IF v_hash IS DISTINCT FROM p_content_hash THEN
        RAISE EXCEPTION 'operation_id reutilizado com conteúdo diferente'
            USING ERRCODE = '23505';
    END IF;
    IF v_status = 'CONFIRMADO' THEN
        RETURN v_result;
    END IF;

    -- Cria saldos ausentes em ordem determinística. A constraint única ativa
    -- estoque_atual_produto_id_deposito_id_key serializa criação concorrente.
    FOR v_product_id, v_deposit_id IN
        SELECT DISTINCT (m.value->>'produto_id')::integer, (m.value->>'deposito_id')::integer
          FROM jsonb_array_elements(p_movimentos) AS m(value)
         ORDER BY 1, 2
    LOOP
        INSERT INTO public.estoque_atual (produto_id, deposito_id, saldo_atual)
        VALUES (v_product_id, v_deposit_id, 0)
        ON CONFLICT (produto_id, deposito_id) DO NOTHING;
    END LOOP;

    -- Bloqueia todos os saldos envolvidos antes de aplicar qualquer efeito.
    PERFORM 1
      FROM public.estoque_atual s
      JOIN (
          SELECT DISTINCT (m.value->>'produto_id')::integer AS produto_id,
                          (m.value->>'deposito_id')::integer AS deposito_id
            FROM jsonb_array_elements(p_movimentos) AS m(value)
      ) keys USING (produto_id, deposito_id)
     ORDER BY s.produto_id, s.deposito_id
     FOR UPDATE OF s;

    FOR v_move IN SELECT value FROM jsonb_array_elements(p_movimentos)
    LOOP
        v_product_id := nullif(v_move->>'produto_id', '')::integer;
        v_deposit_id := nullif(v_move->>'deposito_id', '')::integer;
        v_type := nullif(trim(v_move->>'tipo_movimentacao'), '');
        v_quantity := nullif(v_move->>'quantidade', '')::numeric;

        IF v_product_id IS NULL OR v_deposit_id IS NULL OR v_type IS NULL
           OR v_quantity IS NULL OR (v_quantity = 0 AND v_type <> 'BALANCO') THEN
            RAISE EXCEPTION 'Movimento inválido no comando de estoque' USING ERRCODE = '22023';
        END IF;

        SELECT saldo_atual INTO v_before
          FROM public.estoque_atual
         WHERE produto_id = v_product_id AND deposito_id = v_deposit_id;
        IF v_move ? 'expected_saldo'
           AND v_before IS DISTINCT FROM (v_move->>'expected_saldo')::numeric THEN
            RAISE EXCEPTION 'Versão do saldo alterada para produto % no depósito %', v_product_id, v_deposit_id
                USING ERRCODE = '40001';
        END IF;
        v_after := CASE WHEN v_type = 'BALANCO' THEN v_quantity ELSE v_before + v_quantity END;
        UPDATE public.estoque_atual
           SET saldo_atual = v_after,
               ultima_atualizacao = now(),
               updated_at = now()
         WHERE produto_id = v_product_id AND deposito_id = v_deposit_id;

        INSERT INTO public.movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            documento_referencia, correlation_id, operation_id, origem_tipo,
            item_demanda_id, estagio, data_movimentacao
        ) VALUES (
            v_product_id, v_deposit_id, v_type, v_after - v_before,
            v_before, v_after, v_move->>'motivo', p_actor_id,
            v_move->>'documento_referencia',
            coalesce(nullif(v_move->>'correlation_id', '')::uuid, p_operation_id),
            p_operation_id,
            nullif(v_move->>'origem_tipo', '')::integer,
            nullif(v_move->>'item_demanda_id', '')::integer,
            v_move->>'estagio', now()
        ) RETURNING id INTO v_move_id;

        v_movements := v_movements || jsonb_build_array(jsonb_build_object(
            'movimento_id', v_move_id,
            'produto_id', v_product_id,
            'deposito_id', v_deposit_id,
            'tipo_movimentacao', v_type,
            'quantidade', v_after - v_before,
            'saldo_antes', v_before,
            'saldo_depois', v_after
        ));
    END LOOP;

    SELECT coalesce(jsonb_agg(jsonb_build_object(
               'produto_id', s.produto_id,
               'deposito_id', s.deposito_id,
               'saldo_atual', s.saldo_atual,
               'reservado', s.reservado,
               'disponivel', s.disponivel
           ) ORDER BY s.produto_id, s.deposito_id), '[]'::jsonb)
      INTO v_balances
      FROM public.estoque_atual s
      JOIN (
          SELECT DISTINCT (m.value->>'produto_id')::integer AS produto_id,
                          (m.value->>'deposito_id')::integer AS deposito_id
            FROM jsonb_array_elements(p_movimentos) AS m(value)
      ) keys USING (produto_id, deposito_id);

    v_result := jsonb_build_object(
        'operation_id', p_operation_id,
        'status', 'CONFIRMADO',
        'movimentos', v_movements,
        'saldos', v_balances,
        'confirmed_at', now()
    );

    UPDATE public.estoque_operacoes
       SET status = 'CONFIRMADO', result = v_result, confirmed_at = now()
     WHERE operation_id = p_operation_id;

    RETURN v_result;
END;
$function$;

REVOKE ALL ON FUNCTION public.executar_comando_estoque(uuid, text, text, jsonb, integer, jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.executar_comando_estoque(uuid, text, text, jsonb, integer, jsonb)
    TO service_role;
