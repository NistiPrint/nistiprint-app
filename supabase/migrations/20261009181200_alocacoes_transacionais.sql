-- Reserva vinculada ao item e consumo proporcional no commit do movimento.
ALTER TABLE public.demanda_alocacoes_estoque
    ADD COLUMN IF NOT EXISTS deposito_id integer REFERENCES public.depositos(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS operation_id uuid REFERENCES public.estoque_operacoes(operation_id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS movimento_id integer REFERENCES public.movimentacoes_estoque(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS quantidade_consumida numeric NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS quantidade_liberada numeric NOT NULL DEFAULT 0;

ALTER TABLE public.demanda_alocacoes_estoque
    ADD CONSTRAINT demanda_alocacoes_quantidades_check
    CHECK (quantidade_alocada > 0 AND quantidade_consumida >= 0 AND quantidade_liberada >= 0
           AND quantidade_consumida + quantidade_liberada <= quantidade_alocada);

CREATE INDEX IF NOT EXISTS ix_demanda_alocacoes_item_produto_deposito
    ON public.demanda_alocacoes_estoque(item_id, produto_id, deposito_id, created_at)
    WHERE status = 'PENDENTE';
CREATE INDEX IF NOT EXISTS ix_demanda_alocacoes_operation
    ON public.demanda_alocacoes_estoque(operation_id)
    WHERE operation_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.consumir_reserva_por_movimento()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_allocation record;
    v_remaining numeric := abs(NEW.quantidade);
    v_take numeric;
    v_product text := NEW.produto_id::text;
BEGIN
    IF NEW.tipo_movimentacao <> 'CONS_INT'
       OR NEW.item_demanda_id IS NULL
       OR coalesce(NEW.motivo, '') ILIKE 'Consumo JIT%'
       OR NEW.quantidade >= 0 THEN
        RETURN NEW;
    END IF;

    FOR v_allocation IN
        SELECT id, quantidade_alocada, quantidade_consumida, quantidade_liberada
          FROM public.demanda_alocacoes_estoque
         WHERE item_id = NEW.item_demanda_id::text
           AND produto_id = v_product
           AND (deposito_id IS NULL OR deposito_id = NEW.deposito_id)
           AND status = 'PENDENTE'
           AND quantidade_alocada > quantidade_consumida + quantidade_liberada
         ORDER BY created_at, id
         FOR UPDATE
    LOOP
        EXIT WHEN v_remaining <= 0;
        v_take := least(v_remaining,
            v_allocation.quantidade_alocada - v_allocation.quantidade_consumida - v_allocation.quantidade_liberada);
        UPDATE public.demanda_alocacoes_estoque
           SET quantidade_consumida = quantidade_consumida + v_take,
               status = CASE WHEN quantidade_consumida + v_take + quantidade_liberada >= quantidade_alocada
                             THEN 'PROCESSADA' ELSE 'PENDENTE' END,
               processed_at = CASE WHEN quantidade_consumida + v_take + quantidade_liberada >= quantidade_alocada
                                   THEN now() ELSE processed_at END,
               movimento_id = NEW.id,
               operation_id = NEW.operation_id
         WHERE id = v_allocation.id;
        UPDATE public.estoque_atual
           SET reservado = greatest(0, coalesce(reservado, 0) - v_take),
               updated_at = now(), ultima_atualizacao = now()
         WHERE produto_id = NEW.produto_id AND deposito_id = NEW.deposito_id;
        v_remaining := v_remaining - v_take;
    END LOOP;
    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS trg_consumir_reserva_por_movimento ON public.movimentacoes_estoque;
CREATE TRIGGER trg_consumir_reserva_por_movimento
    AFTER INSERT ON public.movimentacoes_estoque
    FOR EACH ROW EXECUTE FUNCTION public.consumir_reserva_por_movimento();

CREATE OR REPLACE FUNCTION public.vincular_alocacao_operacao_movimento()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
BEGIN
    IF NEW.operation_id IS NOT NULL AND NEW.operation_id IS DISTINCT FROM OLD.operation_id THEN
        UPDATE public.demanda_alocacoes_estoque
           SET operation_id = NEW.operation_id
         WHERE movimento_id = NEW.id AND operation_id IS DISTINCT FROM NEW.operation_id;
    END IF;
    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS trg_vincular_alocacao_operacao_movimento ON public.movimentacoes_estoque;
CREATE TRIGGER trg_vincular_alocacao_operacao_movimento
    AFTER UPDATE OF operation_id ON public.movimentacoes_estoque
    FOR EACH ROW EXECUTE FUNCTION public.vincular_alocacao_operacao_movimento();

CREATE OR REPLACE FUNCTION public.reservar_alocacoes_estoque(
    p_operation_id uuid, p_content_hash text, p_source jsonb, p_actor_id integer,
    p_deposito_id integer, p_allocations jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_hash text;
    v_status text;
    v_result jsonb;
    v_row jsonb;
    v_product integer;
    v_quantity numeric;
    v_item_id text;
    v_demanda_id text;
    v_correlation text;
    v_stock jsonb := '[]'::jsonb;
BEGIN
    IF p_operation_id IS NULL OR p_content_hash !~ '^[0-9a-f]{64}$'
       OR p_deposito_id IS NULL OR jsonb_typeof(p_allocations) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_allocations) = 0 THEN
        RAISE EXCEPTION 'Contrato de reserva inválido' USING ERRCODE = '22023';
    END IF;
    INSERT INTO public.estoque_operacoes(operation_id, command_type, content_hash, source, actor_id)
    VALUES (p_operation_id, 'RESERVA', p_content_hash, coalesce(p_source, '{}'::jsonb), p_actor_id)
    ON CONFLICT (operation_id) DO NOTHING;
    SELECT content_hash, status, result INTO v_hash, v_status, v_result
      FROM public.estoque_operacoes WHERE operation_id = p_operation_id FOR UPDATE;
    IF v_hash IS DISTINCT FROM p_content_hash THEN
        RAISE EXCEPTION 'operation_id de reserva reutilizado com conteúdo diferente' USING ERRCODE = '23505';
    END IF;
    IF v_status = 'CONFIRMADO' THEN RETURN v_result; END IF;

    FOR v_product IN
        SELECT DISTINCT (value->>'produto_id')::integer
          FROM jsonb_array_elements(p_allocations) ORDER BY 1
    LOOP
        INSERT INTO public.estoque_atual(produto_id, deposito_id, saldo_atual)
        VALUES (v_product, p_deposito_id, 0)
        ON CONFLICT (produto_id, deposito_id) DO NOTHING;
    END LOOP;
    PERFORM 1 FROM public.estoque_atual s
     WHERE s.deposito_id = p_deposito_id
       AND s.produto_id IN (SELECT DISTINCT (value->>'produto_id')::integer FROM jsonb_array_elements(p_allocations))
     ORDER BY s.produto_id, s.deposito_id FOR UPDATE;

    FOR v_row IN SELECT value FROM jsonb_array_elements(p_allocations)
    LOOP
        v_product := nullif(v_row->>'produto_id', '')::integer;
        v_quantity := nullif(v_row->>'quantidade', '')::numeric;
        v_item_id := nullif(v_row->>'item_id', '');
        v_demanda_id := nullif(v_row->>'demanda_id', '');
        v_correlation := nullif(v_row->>'correlation_id', '');
        IF v_product IS NULL OR v_quantity IS NULL OR v_quantity <= 0
           OR v_item_id IS NULL OR v_demanda_id IS NULL OR v_correlation IS NULL THEN
            RAISE EXCEPTION 'Alocação inválida' USING ERRCODE = '22023';
        END IF;
        UPDATE public.estoque_atual
           SET reservado = coalesce(reservado, 0) + v_quantity,
               updated_at = now(), ultima_atualizacao = now()
         WHERE produto_id = v_product AND deposito_id = p_deposito_id;
        INSERT INTO public.demanda_alocacoes_estoque(
            demanda_id, item_id, produto_id, correlation_id, quantidade_alocada,
            tipo_alocacao, processo_origem, status, metadata, deposito_id, operation_id
        ) VALUES (
            v_demanda_id, v_item_id, v_product::text, v_correlation, v_quantity,
            'MANUAL_DASHBOARD', 'CONTROLE_PRODUCAO', 'PENDENTE',
            jsonb_build_object('actor_id', p_actor_id), p_deposito_id, p_operation_id
        );
        v_stock := v_stock || jsonb_build_array(jsonb_build_object(
            'produto_id', v_product, 'deposito_id', p_deposito_id,
            'item_id', v_item_id, 'quantidade', v_quantity
        ));
    END LOOP;
    v_result := jsonb_build_object('operation_id', p_operation_id, 'status', 'CONFIRMADO',
                                   'alocacoes', v_stock, 'confirmed_at', now());
    UPDATE public.estoque_operacoes SET status = 'CONFIRMADO', result = v_result, confirmed_at = now()
     WHERE operation_id = p_operation_id;
    RETURN v_result;
END;
$function$;

REVOKE ALL ON FUNCTION public.consumir_reserva_por_movimento() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.vincular_alocacao_operacao_movimento() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reservar_alocacoes_estoque(uuid, text, jsonb, integer, integer, jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reservar_alocacoes_estoque(uuid, text, jsonb, integer, integer, jsonb)
    TO service_role;
