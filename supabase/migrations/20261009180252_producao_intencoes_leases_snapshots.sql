-- Intenção de produção, evento e lease de reconciliação recuperáveis.

ALTER TABLE public.itens_demanda
    ADD COLUMN IF NOT EXISTS operational_revision integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estoque_lease_worker_id text,
    ADD COLUMN IF NOT EXISTS estoque_lease_token uuid,
    ADD COLUMN IF NOT EXISTS estoque_lease_expires_at timestamptz,
    ADD COLUMN IF NOT EXISTS estoque_lease_attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS estoque_lease_next_attempt_at timestamptz,
    ADD COLUMN IF NOT EXISTS estoque_lease_last_error text;

ALTER TABLE public.eventos_producao_v2
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'PENDENTE',
    ADD COLUMN IF NOT EXISTS worker_id text,
    ADD COLUMN IF NOT EXISTS lease_token uuid,
    ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz,
    ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz,
    ADD COLUMN IF NOT EXISTS last_error text,
    ADD COLUMN IF NOT EXISTS intent_revision integer,
    ADD COLUMN IF NOT EXISTS intent_payload jsonb;

UPDATE public.eventos_producao_v2
   SET status = CASE WHEN processado THEN 'CONCLUIDO' ELSE 'PENDENTE' END
 WHERE status IS NULL OR status = 'PENDENTE' AND processado;

ALTER TABLE public.eventos_producao_v2
    ADD CONSTRAINT eventos_producao_v2_status_check
    CHECK (status IN ('PENDENTE', 'PROCESSANDO', 'CONCLUIDO', 'FALHOU'));

CREATE UNIQUE INDEX IF NOT EXISTS ux_eventos_producao_v2_corr_stage
    ON public.eventos_producao_v2(correlation_id, estagio)
    WHERE correlation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_eventos_producao_v2_recovery
    ON public.eventos_producao_v2(status, next_attempt_at, created_at)
    WHERE status IN ('PENDENTE', 'PROCESSANDO');
CREATE INDEX IF NOT EXISTS ix_eventos_producao_v2_item_status
    ON public.eventos_producao_v2(item_demanda_id, status, created_at);

CREATE TABLE IF NOT EXISTS public.snapshots_reconciliacao (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id integer NOT NULL REFERENCES public.itens_demanda(id) ON DELETE RESTRICT,
    demanda_id integer NOT NULL REFERENCES public.demandas_producao(id) ON DELETE RESTRICT,
    operation_id uuid NOT NULL UNIQUE REFERENCES public.estoque_operacoes(operation_id) ON DELETE RESTRICT,
    correlation_id uuid NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.snapshots_reconciliacao ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.snapshots_reconciliacao FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.snapshots_reconciliacao TO service_role;
CREATE INDEX IF NOT EXISTS ix_snapshots_reconciliacao_item
    ON public.snapshots_reconciliacao(item_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.gravar_intencao_eventos_producao(
    p_item_id integer,
    p_expected_revision integer,
    p_updates jsonb,
    p_eventos jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_item public.itens_demanda%ROWTYPE;
    v_event jsonb;
    v_existing_count integer;
    v_event_count integer;
    v_events jsonb;
    v_allowed text[] := ARRAY[
        'capas_impressas_qtd', 'capas_produzidas_qtd',
        'capas_prontas_retirada_qtd', 'miolos_prontos_retirada_qtd',
        'expedicao_capas_retiradas_qtd', 'expedicao_miolos_retirados_qtd',
        'finalizados_qtd', 'status_item'
    ];
    v_key text;
BEGIN
    IF p_item_id IS NULL OR p_expected_revision IS NULL
       OR jsonb_typeof(p_updates) IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_eventos) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_eventos) = 0 THEN
        RAISE EXCEPTION 'Contrato de intenção de produção inválido' USING ERRCODE = '22023';
    END IF;

    FOR v_key IN SELECT jsonb_object_keys(p_updates)
    LOOP
        IF NOT (v_key = ANY(v_allowed)) THEN
            RAISE EXCEPTION 'Campo de intenção não permitido: %', v_key USING ERRCODE = '22023';
        END IF;
    END LOOP;

    SELECT * INTO v_item FROM public.itens_demanda WHERE id = p_item_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Item de demanda % não encontrado', p_item_id USING ERRCODE = 'P0002';
    END IF;

    SELECT count(*) INTO v_event_count FROM jsonb_array_elements(p_eventos);
    SELECT count(*) INTO v_existing_count
      FROM jsonb_array_elements(p_eventos) requested
      JOIN public.eventos_producao_v2 existing
        ON existing.item_demanda_id = p_item_id
       AND existing.correlation_id = (requested.value->>'correlation_id')::uuid
       AND existing.estagio = requested.value->>'estagio';

    IF v_existing_count > 0 THEN
        IF v_existing_count <> v_event_count OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_eventos) requested
            LEFT JOIN public.eventos_producao_v2 existing
              ON existing.item_demanda_id = p_item_id
             AND existing.correlation_id = (requested.value->>'correlation_id')::uuid
             AND existing.estagio = requested.value->>'estagio'
           WHERE existing.id IS NULL
              OR existing.intent_payload IS DISTINCT FROM p_updates
              OR existing.quantidade_reportada IS DISTINCT FROM (requested.value->>'quantidade_reportada')::numeric
              OR existing.tipo_evento IS DISTINCT FROM requested.value->>'tipo_evento'
        ) THEN
            RAISE EXCEPTION 'Identidade de evento reutilizada com conteúdo diferente ou incompleto'
                USING ERRCODE = '23505';
        END IF;
        SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.created_at, e.id), '[]'::jsonb)
          INTO v_events FROM public.eventos_producao_v2 e
         WHERE e.item_demanda_id = p_item_id
           AND EXISTS (
               SELECT 1 FROM jsonb_array_elements(p_eventos) requested
                WHERE e.correlation_id = (requested.value->>'correlation_id')::uuid
                  AND e.estagio = requested.value->>'estagio'
           );
        RETURN jsonb_build_object('success', true, 'duplicate', true,
                                  'item', to_jsonb(v_item), 'eventos', v_events,
                                  'revision', v_item.operational_revision);
    END IF;

    IF v_item.operational_revision <> p_expected_revision THEN
        RAISE EXCEPTION 'Revisão do item mudou de % para %', p_expected_revision, v_item.operational_revision
            USING ERRCODE = '40001';
    END IF;

    UPDATE public.itens_demanda i SET
        capas_impressas_qtd = CASE WHEN p_updates ? 'capas_impressas_qtd' THEN (p_updates->>'capas_impressas_qtd')::numeric ELSE i.capas_impressas_qtd END,
        capas_produzidas_qtd = CASE WHEN p_updates ? 'capas_produzidas_qtd' THEN (p_updates->>'capas_produzidas_qtd')::numeric ELSE i.capas_produzidas_qtd END,
        capas_prontas_retirada_qtd = CASE WHEN p_updates ? 'capas_prontas_retirada_qtd' THEN (p_updates->>'capas_prontas_retirada_qtd')::numeric ELSE i.capas_prontas_retirada_qtd END,
        miolos_prontos_retirada_qtd = CASE WHEN p_updates ? 'miolos_prontos_retirada_qtd' THEN (p_updates->>'miolos_prontos_retirada_qtd')::numeric ELSE i.miolos_prontos_retirada_qtd END,
        expedicao_capas_retiradas_qtd = CASE WHEN p_updates ? 'expedicao_capas_retiradas_qtd' THEN (p_updates->>'expedicao_capas_retiradas_qtd')::numeric ELSE i.expedicao_capas_retiradas_qtd END,
        expedicao_miolos_retirados_qtd = CASE WHEN p_updates ? 'expedicao_miolos_retirados_qtd' THEN (p_updates->>'expedicao_miolos_retirados_qtd')::numeric ELSE i.expedicao_miolos_retirados_qtd END,
        finalizados_qtd = CASE WHEN p_updates ? 'finalizados_qtd' THEN (p_updates->>'finalizados_qtd')::numeric ELSE i.finalizados_qtd END,
        status_item = CASE WHEN p_updates ? 'status_item' THEN p_updates->>'status_item' ELSE i.status_item END,
        operational_revision = i.operational_revision + 1,
        updated_at = now()
     WHERE i.id = p_item_id
     RETURNING * INTO v_item;

    FOR v_event IN SELECT value FROM jsonb_array_elements(p_eventos)
    LOOP
        IF nullif(v_event->>'estagio', '') IS NULL
           OR nullif(v_event->>'tipo_evento', '') NOT IN ('SINAL', 'LIQUIDACAO', 'FINALIZACAO', 'BOM_RECURSIVO_APOS_DIRETO')
           OR nullif(v_event->>'correlation_id', '') IS NULL
           OR nullif(v_event->>'quantidade_reportada', '') IS NULL
           OR (v_event->>'quantidade_reportada')::numeric < 0 THEN
            RAISE EXCEPTION 'Evento de produção inválido' USING ERRCODE = '22023';
        END IF;
        INSERT INTO public.eventos_producao_v2 (
            item_demanda_id, demanda_id, estagio, quantidade_reportada,
            tipo_evento, processado, correlation_id, usuario_id, created_at,
            status, intent_revision, intent_payload
        ) VALUES (
            p_item_id, v_item.demanda_id, v_event->>'estagio',
            (v_event->>'quantidade_reportada')::numeric,
            v_event->>'tipo_evento', false,
            (v_event->>'correlation_id')::uuid,
            nullif(v_event->>'usuario_id', '')::integer,
            now(), 'PENDENTE', v_item.operational_revision, p_updates
        );
    END LOOP;

    SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.created_at, e.id), '[]'::jsonb)
      INTO v_events FROM public.eventos_producao_v2 e
     WHERE e.item_demanda_id = p_item_id
       AND EXISTS (
           SELECT 1 FROM jsonb_array_elements(p_eventos) requested
            WHERE e.correlation_id = (requested.value->>'correlation_id')::uuid
              AND e.estagio = requested.value->>'estagio'
       );
    RETURN jsonb_build_object('success', true, 'duplicate', false,
                              'item', to_jsonb(v_item), 'eventos', v_events,
                              'revision', v_item.operational_revision);
END;
$function$;

CREATE OR REPLACE FUNCTION public.claim_eventos_producao(
    p_worker_id text,
    p_limit integer DEFAULT 20,
    p_lease_seconds integer DEFAULT 300
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_item record;
    v_token uuid;
    v_events jsonb;
    v_result jsonb := '[]'::jsonb;
BEGIN
    IF nullif(trim(p_worker_id), '') IS NULL OR p_limit < 1 OR p_lease_seconds < 30 THEN
        RAISE EXCEPTION 'Parâmetros de claim inválidos' USING ERRCODE = '22023';
    END IF;

    FOR v_item IN
        SELECT i.id, i.demanda_id
          FROM public.itens_demanda i
         WHERE (i.estoque_lease_expires_at IS NULL OR i.estoque_lease_expires_at <= now())
           AND (i.estoque_lease_next_attempt_at IS NULL OR i.estoque_lease_next_attempt_at <= now())
           AND EXISTS (
               SELECT 1 FROM public.eventos_producao_v2 e
                WHERE e.item_demanda_id = i.id
                  AND e.status IN ('PENDENTE', 'PROCESSANDO')
                  AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now())
                  AND e.attempts < 8
           )
         ORDER BY i.id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    LOOP
        v_token := gen_random_uuid();
        UPDATE public.itens_demanda
           SET estoque_lease_worker_id = p_worker_id,
               estoque_lease_token = v_token,
               estoque_lease_expires_at = now() + make_interval(secs => p_lease_seconds),
               estoque_lease_attempts = estoque_lease_attempts + 1,
               status_processamento = 'PROCESSANDO'
         WHERE id = v_item.id;

        UPDATE public.eventos_producao_v2
           SET status = 'PENDENTE', processado = false,
               worker_id = NULL, lease_token = NULL, lease_expires_at = NULL
         WHERE item_demanda_id = v_item.id
           AND status = 'PROCESSANDO'
           AND (lease_expires_at IS NULL OR lease_expires_at <= now());

        UPDATE public.eventos_producao_v2
           SET status = 'PROCESSANDO', processado = false,
               worker_id = p_worker_id, lease_token = v_token,
               lease_expires_at = now() + make_interval(secs => p_lease_seconds),
               attempts = attempts + 1, last_error = NULL
         WHERE item_demanda_id = v_item.id
           AND status = 'PENDENTE'
           AND (next_attempt_at IS NULL OR next_attempt_at <= now())
           AND attempts < 8;

        SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.created_at, e.id), '[]'::jsonb)
          INTO v_events FROM public.eventos_producao_v2 e
         WHERE e.item_demanda_id = v_item.id AND e.lease_token = v_token;
        IF jsonb_array_length(v_events) > 0 THEN
            v_result := v_result || jsonb_build_array(jsonb_build_object(
                'item_id', v_item.id, 'demanda_id', v_item.demanda_id,
                'worker_id', p_worker_id, 'lease_token', v_token,
                'lease_expires_at', now() + make_interval(secs => p_lease_seconds),
                'eventos', v_events
            ));
        ELSE
            UPDATE public.itens_demanda SET
                estoque_lease_worker_id = NULL, estoque_lease_token = NULL,
                estoque_lease_expires_at = NULL, status_processamento = 'PENDENTE'
             WHERE id = v_item.id AND estoque_lease_token = v_token;
        END IF;
    END LOOP;
    RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.renew_eventos_producao_lease(
    p_item_id integer, p_worker_id text, p_lease_token uuid, p_lease_seconds integer DEFAULT 300
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
DECLARE v_expiry timestamptz;
BEGIN
    UPDATE public.itens_demanda
       SET estoque_lease_expires_at = now() + make_interval(secs => p_lease_seconds)
     WHERE id = p_item_id AND estoque_lease_worker_id = p_worker_id
       AND estoque_lease_token = p_lease_token AND estoque_lease_expires_at > now()
     RETURNING estoque_lease_expires_at INTO v_expiry;
    IF v_expiry IS NULL THEN RETURN false; END IF;
    UPDATE public.eventos_producao_v2
       SET lease_expires_at = v_expiry
     WHERE item_demanda_id = p_item_id AND worker_id = p_worker_id AND lease_token = p_lease_token
       AND status = 'PROCESSANDO';
    RETURN true;
END;
$function$;

CREATE OR REPLACE FUNCTION public.complete_eventos_producao(
    p_item_id integer, p_worker_id text, p_lease_token uuid, p_event_ids uuid[]
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
DECLARE v_count integer;
BEGIN
    PERFORM 1 FROM public.itens_demanda
     WHERE id = p_item_id AND estoque_lease_worker_id = p_worker_id
       AND estoque_lease_token = p_lease_token AND estoque_lease_expires_at > now()
     FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Lease de produção expirado ou perdido' USING ERRCODE = '40001'; END IF;
    UPDATE public.eventos_producao_v2
       SET status = 'CONCLUIDO', processado = true,
           worker_id = NULL, lease_token = NULL, lease_expires_at = NULL,
           next_attempt_at = NULL, last_error = NULL
     WHERE item_demanda_id = p_item_id AND id = ANY(p_event_ids)
       AND worker_id = p_worker_id AND lease_token = p_lease_token
       AND status = 'PROCESSANDO';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    IF v_count <> cardinality(p_event_ids) THEN
        RAISE EXCEPTION 'Nem todos os eventos pertencem ao lease atual' USING ERRCODE = '40001';
    END IF;
    UPDATE public.itens_demanda
       SET estoque_lease_worker_id = NULL, estoque_lease_token = NULL,
           estoque_lease_expires_at = NULL, estoque_lease_next_attempt_at = NULL,
           estoque_lease_last_error = NULL, status_processamento = 'PENDENTE'
     WHERE id = p_item_id AND estoque_lease_token = p_lease_token;
    RETURN true;
END;
$function$;

CREATE OR REPLACE FUNCTION public.fail_eventos_producao(
    p_item_id integer, p_worker_id text, p_lease_token uuid,
    p_event_ids uuid[], p_error text, p_retry_seconds integer DEFAULT 30
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
DECLARE v_count integer;
BEGIN
    PERFORM 1 FROM public.itens_demanda
     WHERE id = p_item_id AND estoque_lease_worker_id = p_worker_id
       AND estoque_lease_token = p_lease_token
     FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Lease de produção perdido' USING ERRCODE = '40001'; END IF;
    UPDATE public.eventos_producao_v2
       SET status = CASE WHEN attempts >= 8 THEN 'FALHOU' ELSE 'PENDENTE' END,
           processado = false, worker_id = NULL, lease_token = NULL, lease_expires_at = NULL,
           next_attempt_at = CASE WHEN attempts >= 8 THEN NULL ELSE now() + make_interval(secs => greatest(5, p_retry_seconds)) END,
           last_error = left(coalesce(p_error, 'erro de processamento'), 4000)
     WHERE item_demanda_id = p_item_id AND id = ANY(p_event_ids)
       AND worker_id = p_worker_id AND lease_token = p_lease_token
       AND status = 'PROCESSANDO';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    IF v_count <> cardinality(p_event_ids) THEN
        RAISE EXCEPTION 'Nem todos os eventos pertencem ao lease atual' USING ERRCODE = '40001';
    END IF;
    UPDATE public.itens_demanda
       SET estoque_lease_worker_id = NULL, estoque_lease_token = NULL,
           estoque_lease_expires_at = NULL,
           estoque_lease_attempts = estoque_lease_attempts + 1,
           estoque_lease_next_attempt_at = CASE WHEN v_count > 0 THEN now() + make_interval(secs => greatest(5, p_retry_seconds)) END,
           estoque_lease_last_error = left(coalesce(p_error, 'erro de processamento'), 4000),
           status_processamento = 'PENDENTE'
     WHERE id = p_item_id AND estoque_lease_token = p_lease_token;
    RETURN true;
END;
$function$;

CREATE OR REPLACE FUNCTION public.confirmar_reconciliacao_producao(
    p_operation_id uuid,
    p_content_hash text,
    p_item_id integer,
    p_demanda_id integer,
    p_movimentos jsonb,
    p_snapshot jsonb,
    p_correlation_id uuid,
    p_user_id text,
    p_worker_id text,
    p_lease_token uuid,
    p_event_ids uuid[]
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_operation public.estoque_operacoes%ROWTYPE;
    v_result jsonb;
    v_count integer;
BEGIN
    IF p_operation_id IS NULL OR p_content_hash !~ '^[0-9a-f]{64}$'
       OR p_item_id IS NULL OR p_demanda_id IS NULL
       OR jsonb_typeof(p_movimentos) IS DISTINCT FROM 'array'
       OR jsonb_typeof(p_snapshot) IS DISTINCT FROM 'object'
       OR cardinality(p_event_ids) IS NULL OR cardinality(p_event_ids) = 0 THEN
        RAISE EXCEPTION 'Contrato de reconciliação inválido' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.estoque_operacoes(
        operation_id, command_type, content_hash, source, status
    ) VALUES (
        p_operation_id, 'RECONCILIACAO_PRODUCAO', p_content_hash,
        jsonb_build_object('item_id', p_item_id, 'demanda_id', p_demanda_id,
                           'correlation_id', p_correlation_id), 'PROCESSANDO'
    ) ON CONFLICT (operation_id) DO NOTHING;

    SELECT * INTO v_operation FROM public.estoque_operacoes
     WHERE operation_id = p_operation_id FOR UPDATE;
    IF v_operation.content_hash IS DISTINCT FROM p_content_hash
       OR v_operation.command_type <> 'RECONCILIACAO_PRODUCAO' THEN
        RAISE EXCEPTION 'operation_id reutilizado com outro conteúdo' USING ERRCODE = '23505';
    END IF;
    IF v_operation.status = 'CONFIRMADO' THEN
        RETURN v_operation.result || jsonb_build_object('duplicate', true);
    END IF;

    PERFORM 1 FROM public.itens_demanda
     WHERE id = p_item_id AND demanda_id = p_demanda_id
       AND estoque_lease_worker_id = p_worker_id
       AND estoque_lease_token = p_lease_token
       AND estoque_lease_expires_at > now()
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Lease de produção expirado, perdido ou incompatível' USING ERRCODE = '40001';
    END IF;

    PERFORM 1 FROM public.eventos_producao_v2
     WHERE item_demanda_id = p_item_id AND id = ANY(p_event_ids)
       AND worker_id = p_worker_id AND lease_token = p_lease_token
       AND status = 'PROCESSANDO'
     FOR UPDATE;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    IF v_count <> cardinality(p_event_ids) THEN
        RAISE EXCEPTION 'Nem todos os eventos pertencem ao lease atual' USING ERRCODE = '40001';
    END IF;

    v_result := public.reconciliar_item_estoque(
        p_item_id, p_demanda_id, p_movimentos, p_snapshot,
        p_correlation_id, p_user_id
    );
    IF coalesce((v_result->>'sucesso')::boolean, false) IS NOT TRUE THEN
        RAISE EXCEPTION 'Reconciliação falhou: %', coalesce(v_result->>'erro', v_result::text)
            USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO public.snapshots_reconciliacao(
        item_id, demanda_id, operation_id, correlation_id, payload
    ) VALUES (p_item_id, p_demanda_id, p_operation_id, p_correlation_id, p_snapshot);

    UPDATE public.movimentacoes_estoque
       SET operation_id = p_operation_id
     WHERE correlation_id = p_correlation_id AND item_demanda_id = p_item_id
       AND operation_id IS NULL;

    UPDATE public.eventos_producao_v2
       SET status = 'CONCLUIDO', processado = true,
           worker_id = NULL, lease_token = NULL, lease_expires_at = NULL,
           next_attempt_at = NULL, last_error = NULL
     WHERE item_demanda_id = p_item_id AND id = ANY(p_event_ids)
       AND worker_id = p_worker_id AND lease_token = p_lease_token
       AND status = 'PROCESSANDO';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    IF v_count <> cardinality(p_event_ids) THEN
        RAISE EXCEPTION 'Eventos não puderam ser confirmados integralmente' USING ERRCODE = '40001';
    END IF;

    UPDATE public.itens_demanda
       SET estoque_lease_worker_id = NULL, estoque_lease_token = NULL,
           estoque_lease_expires_at = NULL, estoque_lease_next_attempt_at = NULL,
           estoque_lease_last_error = NULL, status_processamento = 'PROCESSADO'
     WHERE id = p_item_id AND estoque_lease_token = p_lease_token;

    v_result := v_result || jsonb_build_object(
        'operation_id', p_operation_id, 'snapshot_id', p_operation_id,
        'duplicate', false
    );
    UPDATE public.estoque_operacoes
       SET status = 'CONFIRMADO', result = v_result, confirmed_at = now()
     WHERE operation_id = p_operation_id;
    RETURN v_result;
END;
$function$;

REVOKE ALL ON FUNCTION public.gravar_intencao_eventos_producao(integer, integer, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.claim_eventos_producao(text, integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.renew_eventos_producao_lease(integer, text, uuid, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.complete_eventos_producao(integer, text, uuid, uuid[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fail_eventos_producao(integer, text, uuid, uuid[], text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.confirmar_reconciliacao_producao(uuid, text, integer, integer, jsonb, jsonb, uuid, text, text, uuid, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.gravar_intencao_eventos_producao(integer, integer, jsonb, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_eventos_producao(text, integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.renew_eventos_producao_lease(integer, text, uuid, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.complete_eventos_producao(integer, text, uuid, uuid[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_eventos_producao(integer, text, uuid, uuid[], text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.confirmar_reconciliacao_producao(uuid, text, integer, integer, jsonb, jsonb, uuid, text, text, uuid, uuid[]) TO service_role;
