CREATE OR REPLACE FUNCTION public.claim_eventos_producao(
    p_worker_id text, p_limit integer DEFAULT 20, p_lease_seconds integer DEFAULT 300
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
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
        SELECT i.id, i.demanda_id FROM public.itens_demanda i
         WHERE (i.estoque_lease_expires_at IS NULL OR i.estoque_lease_expires_at <= now())
           AND (i.estoque_lease_next_attempt_at IS NULL OR i.estoque_lease_next_attempt_at <= now())
           AND EXISTS (
               SELECT 1 FROM public.eventos_producao_v2 e
                WHERE e.item_demanda_id = i.id AND NOT e.processado
                  AND e.status IN ('PENDENTE', 'PROCESSANDO')
                  AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now())
                  AND e.attempts < 8
           )
         ORDER BY i.id FOR UPDATE SKIP LOCKED LIMIT p_limit
    LOOP
        v_token := gen_random_uuid();
        UPDATE public.itens_demanda SET
            estoque_lease_worker_id = p_worker_id, estoque_lease_token = v_token,
            estoque_lease_expires_at = now() + make_interval(secs => p_lease_seconds),
            estoque_lease_attempts = estoque_lease_attempts + 1,
            status_processamento = 'PROCESSANDO'
         WHERE id = v_item.id;
        UPDATE public.eventos_producao_v2 SET
            status = CASE WHEN attempts >= 8 THEN 'FALHOU' ELSE 'PENDENTE' END,
            processado = false, worker_id = NULL, lease_token = NULL, lease_expires_at = NULL
         WHERE item_demanda_id = v_item.id AND NOT processado AND status = 'PROCESSANDO'
           AND (lease_expires_at IS NULL OR lease_expires_at <= now());
        UPDATE public.eventos_producao_v2 SET
            status = 'PROCESSANDO', processado = false, worker_id = p_worker_id,
            lease_token = v_token, lease_expires_at = now() + make_interval(secs => p_lease_seconds),
            attempts = attempts + 1, last_error = NULL
         WHERE item_demanda_id = v_item.id AND NOT processado AND status = 'PENDENTE'
           AND (next_attempt_at IS NULL OR next_attempt_at <= now()) AND attempts < 8;
        SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.created_at, e.id), '[]'::jsonb)
          INTO v_events FROM public.eventos_producao_v2 e
         WHERE e.item_demanda_id = v_item.id AND e.lease_token = v_token;
        IF jsonb_array_length(v_events) > 0 THEN
            v_result := v_result || jsonb_build_array(jsonb_build_object(
                'item_id', v_item.id, 'demanda_id', v_item.demanda_id,
                'worker_id', p_worker_id, 'lease_token', v_token,
                'lease_expires_at', now() + make_interval(secs => p_lease_seconds),
                'eventos', v_events));
        ELSE
            UPDATE public.itens_demanda SET estoque_lease_worker_id = NULL,
                estoque_lease_token = NULL, estoque_lease_expires_at = NULL,
                status_processamento = 'PENDENTE' WHERE id = v_item.id AND estoque_lease_token = v_token;
        END IF;
    END LOOP;
    RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.complete_eventos_producao(
    p_item_id integer, p_worker_id text, p_lease_token uuid, p_event_ids uuid[]
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
DECLARE v_count integer;
BEGIN
    PERFORM 1 FROM public.itens_demanda WHERE id = p_item_id
      AND estoque_lease_worker_id = p_worker_id AND estoque_lease_token = p_lease_token
      AND estoque_lease_expires_at > now() FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Lease de produção expirado ou perdido' USING ERRCODE = '40001'; END IF;
    UPDATE public.eventos_producao_v2 SET status = 'CONCLUIDO', processado = true,
      worker_id = NULL, lease_token = NULL, lease_expires_at = NULL,
      next_attempt_at = NULL, last_error = NULL
     WHERE item_demanda_id = p_item_id AND id = ANY(p_event_ids)
       AND worker_id = p_worker_id AND lease_token = p_lease_token AND status = 'PROCESSANDO';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    IF v_count <> cardinality(p_event_ids) THEN
      RAISE EXCEPTION 'Nem todos os eventos pertencem ao lease atual' USING ERRCODE = '40001';
    END IF;
    UPDATE public.itens_demanda SET estoque_lease_worker_id = NULL, estoque_lease_token = NULL,
      estoque_lease_expires_at = NULL, estoque_lease_next_attempt_at = NULL,
      estoque_lease_last_error = NULL, status_processamento = 'PROCESSADO'
     WHERE id = p_item_id AND estoque_lease_token = p_lease_token;
    RETURN true;
END;
$function$;

CREATE OR REPLACE FUNCTION public.renew_eventos_producao_lease(
    p_item_id integer, p_worker_id text, p_lease_token uuid, p_lease_seconds integer DEFAULT 300
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
DECLARE v_expiry timestamptz;
BEGIN
    IF p_lease_seconds < 30 THEN RAISE EXCEPTION 'Lease deve ter ao menos 30 segundos' USING ERRCODE = '22023'; END IF;
    UPDATE public.itens_demanda SET estoque_lease_expires_at = now() + make_interval(secs => p_lease_seconds)
     WHERE id = p_item_id AND estoque_lease_worker_id = p_worker_id
       AND estoque_lease_token = p_lease_token AND estoque_lease_expires_at > now()
     RETURNING estoque_lease_expires_at INTO v_expiry;
    IF v_expiry IS NULL THEN RETURN false; END IF;
    UPDATE public.eventos_producao_v2 SET lease_expires_at = v_expiry
     WHERE item_demanda_id = p_item_id AND worker_id = p_worker_id
       AND lease_token = p_lease_token AND status = 'PROCESSANDO';
    RETURN true;
END;
$function$;
