-- Pin the immutable effective BOM in the same transaction as its first
-- production intent and event. The trailing default preserves old 4-arg RPC
-- callers while they are being drained from the deployment.
DROP FUNCTION public.gravar_intencao_eventos_producao(integer,integer,jsonb,jsonb);

CREATE FUNCTION public.gravar_intencao_eventos_producao(
    p_item_id integer,
    p_expected_revision integer,
    p_updates jsonb,
    p_eventos jsonb,
    p_bom_version_id uuid DEFAULT NULL
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

    IF p_bom_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.bom_efetiva_versoes b
         WHERE b.id = p_bom_version_id AND b.produto_id = v_item.produto_id
    ) THEN
        RAISE EXCEPTION 'Versão de BOM não pertence ao produto do item %', p_item_id
            USING ERRCODE = '23503';
    END IF;
    IF v_item.bom_version_id IS NOT NULL AND p_bom_version_id IS NOT NULL
       AND v_item.bom_version_id IS DISTINCT FROM p_bom_version_id THEN
        RAISE EXCEPTION 'Versão de BOM do item mudou durante a gravação da intenção'
            USING ERRCODE = '40001';
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

        IF v_item.bom_version_id IS NULL AND p_bom_version_id IS NOT NULL THEN
            UPDATE public.itens_demanda
               SET bom_version_id=p_bom_version_id,
                   operational_revision=operational_revision+1,
                   updated_at=now()
             WHERE id=p_item_id
             RETURNING * INTO v_item;
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
        bom_version_id = coalesce(i.bom_version_id,p_bom_version_id),
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

REVOKE ALL ON FUNCTION public.gravar_intencao_eventos_producao(integer,integer,jsonb,jsonb,uuid)
    FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.gravar_intencao_eventos_producao(integer,integer,jsonb,jsonb,uuid)
    TO service_role;

NOTIFY pgrst, 'reload schema';
