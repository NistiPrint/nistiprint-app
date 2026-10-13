CREATE OR REPLACE FUNCTION public.claim_eventos_producao(
    p_worker_id text, p_limit integer, p_lease_seconds integer, p_item_id integer
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
         WHERE (p_item_id IS NULL OR i.id = p_item_id)
           AND (i.estoque_lease_expires_at IS NULL OR i.estoque_lease_expires_at <= now())
           AND (i.estoque_lease_next_attempt_at IS NULL OR i.estoque_lease_next_attempt_at <= now())
           AND EXISTS (
               SELECT 1 FROM public.eventos_producao_v2 e
                WHERE e.item_demanda_id = i.id AND NOT e.processado
                  AND e.status IN ('PENDENTE', 'PROCESSANDO')
                  AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now()) AND e.attempts < 8
           )
         ORDER BY i.id FOR UPDATE SKIP LOCKED LIMIT p_limit
    LOOP
        v_token := gen_random_uuid();
        UPDATE public.itens_demanda SET estoque_lease_worker_id = p_worker_id,
          estoque_lease_token = v_token,
          estoque_lease_expires_at = now() + make_interval(secs => p_lease_seconds),
          estoque_lease_attempts = estoque_lease_attempts + 1, status_processamento = 'PROCESSANDO'
         WHERE id = v_item.id;
        UPDATE public.eventos_producao_v2 SET
          status = CASE WHEN attempts >= 8 THEN 'FALHOU' ELSE 'PENDENTE' END,
          processado = false, worker_id = NULL, lease_token = NULL, lease_expires_at = NULL
         WHERE item_demanda_id = v_item.id AND NOT processado AND status = 'PROCESSANDO'
           AND (lease_expires_at IS NULL OR lease_expires_at <= now());
        UPDATE public.eventos_producao_v2 SET status = 'PROCESSANDO', processado = false,
          worker_id = p_worker_id, lease_token = v_token,
          lease_expires_at = now() + make_interval(secs => p_lease_seconds),
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
              'lease_expires_at', now() + make_interval(secs => p_lease_seconds), 'eventos', v_events));
        ELSE
            UPDATE public.itens_demanda SET estoque_lease_worker_id = NULL, estoque_lease_token = NULL,
              estoque_lease_expires_at = NULL, status_processamento = 'PENDENTE'
             WHERE id = v_item.id AND estoque_lease_token = v_token;
        END IF;
    END LOOP;
    RETURN v_result;
END;
$function$;
REVOKE ALL ON FUNCTION public.claim_eventos_producao(text, integer, integer, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_eventos_producao(text, integer, integer, integer)
  TO service_role;
