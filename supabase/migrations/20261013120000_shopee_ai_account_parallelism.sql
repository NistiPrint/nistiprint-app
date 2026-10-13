-- Durable per-account execution for Shopee AI batches.
ALTER TABLE public.execucoes_ai_batch
    ADD COLUMN IF NOT EXISTS force boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS public.execucoes_ai_batch_conta (
    batch_id uuid NOT NULL REFERENCES public.execucoes_ai_batch(id) ON DELETE CASCADE,
    account_key text NOT NULL,
    marketplace_integration_id integer REFERENCES public.installed_integrations(id) ON DELETE SET NULL,
    pedido_ids bigint[] NOT NULL,
    force boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'PENDENTE'
        CHECK (status IN ('PENDENTE', 'RODANDO', 'CONCLUIDO', 'ERRO')),
    run_token uuid,
    lease_until timestamptz,
    available_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    PRIMARY KEY (batch_id, account_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_shopee_ai_account_running
    ON public.execucoes_ai_batch_conta(account_key) WHERE status = 'RODANDO';
CREATE INDEX IF NOT EXISTS ix_shopee_ai_account_recovery
    ON public.execucoes_ai_batch_conta(status, available_at, lease_until);

CREATE TABLE IF NOT EXISTS public.execucoes_ai_batch_pedido (
    batch_id uuid NOT NULL,
    account_key text NOT NULL,
    pedido_id bigint NOT NULL REFERENCES public.pedidos(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'PENDENTE'
        CHECK (status IN ('PENDENTE', 'RODANDO', 'OK', 'ERRO', 'ADIADO', 'UP_TO_DATE')),
    attempts integer NOT NULL DEFAULT 0,
    execution_token uuid,
    started_at timestamptz,
    finished_at timestamptz,
    available_at timestamptz NOT NULL DEFAULT now(),
    duration_ms integer,
    error_message text,
    PRIMARY KEY (batch_id, pedido_id),
    FOREIGN KEY (batch_id, account_key)
        REFERENCES public.execucoes_ai_batch_conta(batch_id, account_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_shopee_ai_order_recovery
    ON public.execucoes_ai_batch_pedido(status, available_at);

ALTER TABLE public.execucoes_ai_batch_conta ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.execucoes_ai_batch_pedido ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.execucoes_ai_batch_conta, public.execucoes_ai_batch_pedido
    FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.execucoes_ai_batch_conta, public.execucoes_ai_batch_pedido
    TO service_role;

-- Convert only unfinished legacy batches. Existing completed item rows remain
-- the public history and are not re-enqueued.
INSERT INTO public.execucoes_ai_batch_conta
    (batch_id, account_key, marketplace_integration_id, pedido_ids, force)
SELECT b.id,
       COALESCE(p.marketplace_integration_id::text, 'legacy'),
       p.marketplace_integration_id,
       array_agg(pedido_id ORDER BY pedido_id), false
  FROM public.execucoes_ai_batch b
 CROSS JOIN LATERAL unnest(b.pedido_ids) AS batch_order(pedido_id)
  JOIN public.pedidos p ON p.id = batch_order.pedido_id
 WHERE b.status IN ('PENDENTE', 'RODANDO')
   AND NOT EXISTS (
       SELECT 1 FROM public.execucoes_ai_item i
        WHERE i.batch_id = b.id AND i.pedido_id = batch_order.pedido_id
   )
 GROUP BY b.id, COALESCE(p.marketplace_integration_id::text, 'legacy'),
          p.marketplace_integration_id
ON CONFLICT (batch_id, account_key) DO NOTHING;

INSERT INTO public.execucoes_ai_batch_pedido (batch_id, account_key, pedido_id)
SELECT c.batch_id, c.account_key, unnest(c.pedido_ids)
  FROM public.execucoes_ai_batch_conta c
 WHERE c.status = 'PENDENTE'
ON CONFLICT (batch_id, pedido_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.reivindicar_lote_ai_conta(
    p_batch_id uuid, p_account_key text, p_run_token uuid
) RETURNS SETOF public.execucoes_ai_batch_conta
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_run public.execucoes_ai_batch_conta;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('shopee-ai:' || p_account_key, 0));
    UPDATE public.execucoes_ai_batch_conta
       SET status = 'PENDENTE', run_token = NULL, lease_until = NULL,
           available_at = now()
     WHERE account_key = p_account_key AND status = 'RODANDO'
       AND lease_until <= now();
    SELECT * INTO v_run FROM public.execucoes_ai_batch_conta
     WHERE batch_id = p_batch_id AND account_key = p_account_key FOR UPDATE;
    IF NOT FOUND OR v_run.status IN ('CONCLUIDO', 'ERRO') THEN RETURN; END IF;
    IF v_run.available_at > now() THEN RETURN; END IF;
    IF v_run.status = 'RODANDO' AND v_run.lease_until > now() THEN RETURN; END IF;
    IF EXISTS (SELECT 1 FROM public.execucoes_ai_batch_conta
                WHERE account_key = p_account_key AND status = 'RODANDO'
                  AND lease_until > now() AND batch_id <> p_batch_id) THEN RETURN; END IF;
    UPDATE public.execucoes_ai_batch_conta
       SET status = 'RODANDO', run_token = p_run_token,
           lease_until = now() + interval '5 minutes',
           started_at = COALESCE(started_at, now())
     WHERE batch_id = p_batch_id AND account_key = p_account_key
     RETURNING * INTO v_run;
    UPDATE public.execucoes_ai_batch_pedido
       SET status = 'PENDENTE', execution_token = NULL,
           available_at = now(), error_message = COALESCE(error_message, 'Retomado após expiração do worker.')
     WHERE batch_id = p_batch_id AND account_key = p_account_key AND status = 'RODANDO';
    UPDATE public.execucoes_ai_batch SET status = 'RODANDO' WHERE id = p_batch_id
       AND status = 'PENDENTE';
    RETURN NEXT v_run;
END $$;

CREATE OR REPLACE FUNCTION public.renovar_lote_ai_conta(
    p_batch_id uuid, p_account_key text, p_run_token uuid
) RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    UPDATE public.execucoes_ai_batch_conta
       SET lease_until = now() + interval '5 minutes'
     WHERE batch_id = p_batch_id AND account_key = p_account_key
       AND status = 'RODANDO' AND run_token = p_run_token
    RETURNING true
$$;

CREATE OR REPLACE FUNCTION public.reivindicar_item_ai(
    p_batch_id uuid, p_account_key text, p_pedido_id bigint, p_run_token uuid
) RETURNS SETOF public.execucoes_ai_batch_pedido
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.execucoes_ai_batch_pedido;
BEGIN
    UPDATE public.execucoes_ai_batch_pedido
       SET status = 'RODANDO', attempts = attempts + 1,
           execution_token = p_run_token, started_at = now(), error_message = NULL
     WHERE batch_id = p_batch_id AND account_key = p_account_key
       AND pedido_id = p_pedido_id AND status = 'PENDENTE'
       AND available_at <= now()
       AND EXISTS (SELECT 1 FROM public.execucoes_ai_batch_conta c
                    WHERE c.batch_id = p_batch_id AND c.account_key = p_account_key
                      AND c.status = 'RODANDO' AND c.run_token = p_run_token)
    RETURNING * INTO v_item;
    IF FOUND THEN RETURN NEXT v_item; END IF;
END $$;

CREATE OR REPLACE FUNCTION public.adiar_item_ai(
    p_batch_id uuid, p_account_key text, p_pedido_id bigint,
    p_run_token uuid, p_error text, p_delay_seconds integer
) RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    UPDATE public.execucoes_ai_batch_pedido
       SET status = 'PENDENTE', execution_token = NULL,
           available_at = now() + make_interval(secs => p_delay_seconds),
           error_message = p_error
     WHERE batch_id = p_batch_id AND account_key = p_account_key
       AND pedido_id = p_pedido_id AND status = 'RODANDO'
       AND execution_token = p_run_token
    RETURNING true
$$;

CREATE OR REPLACE FUNCTION public.concluir_item_ai(
    p_batch_id uuid, p_account_key text, p_pedido_id bigint, p_run_token uuid,
    p_status text, p_error text, p_duration_ms integer, p_shopee_order_sn text,
    p_personalizations jsonb, p_log jsonb
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_item public.execucoes_ai_batch_pedido;
BEGIN
    SELECT * INTO v_item FROM public.execucoes_ai_batch_pedido
     WHERE batch_id = p_batch_id AND account_key = p_account_key
       AND pedido_id = p_pedido_id AND status = 'RODANDO'
       AND execution_token = p_run_token FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    IF p_status = 'OK' THEN
        DELETE FROM public.personalizacoes_pedido WHERE shopee_order_sn = p_shopee_order_sn;
        INSERT INTO public.personalizacoes_pedido
            (codigo_pedido, shopee_order_sn, bling_id, item_pedido_id, item_id,
             item_description, customization_name, customization_initial,
             name_source_message_id, status, reasoning, detalhes_personalizacao,
             metadata, updated_at)
        SELECT codigo_pedido, shopee_order_sn, bling_id, item_pedido_id, item_id,
               item_description, customization_name, customization_initial,
               name_source_message_id, status, reasoning, detalhes_personalizacao,
               metadata, updated_at
          FROM jsonb_populate_recordset(NULL::public.personalizacoes_pedido,
                COALESCE(p_personalizations, '[]'::jsonb));
        IF p_log IS NOT NULL THEN
          INSERT INTO public.logs_execucao_ia
            (order_sn, executed_at, input_data, chat_context,
             extracted_personalization, model_result, status, error_message, metadata)
        SELECT order_sn, executed_at, input_data, chat_context,
               extracted_personalization, model_result, status, error_message, metadata
          FROM jsonb_populate_record(NULL::public.logs_execucao_ia, p_log);
        END IF;
    ELSIF p_log IS NOT NULL THEN
        INSERT INTO public.logs_execucao_ia
            (order_sn, executed_at, input_data, chat_context,
             extracted_personalization, model_result, status, error_message, metadata)
        SELECT order_sn, executed_at, input_data, chat_context,
               extracted_personalization, model_result, status, error_message, metadata
          FROM jsonb_populate_record(NULL::public.logs_execucao_ia, p_log);
    END IF;
    UPDATE public.execucoes_ai_batch_pedido
       SET status = p_status, error_message = p_error, duration_ms = p_duration_ms,
           finished_at = now(), execution_token = NULL
     WHERE batch_id = p_batch_id AND pedido_id = p_pedido_id;
    INSERT INTO public.execucoes_ai_item (batch_id, pedido_id, status, erro, duracao_ms)
    VALUES (p_batch_id, p_pedido_id, p_status, p_error, p_duration_ms);
    UPDATE public.execucoes_ai_batch
       SET processados = COALESCE(processados, 0) + 1,
           sucesso = COALESCE(sucesso, 0) + CASE WHEN p_status IN ('OK', 'UP_TO_DATE') THEN 1 ELSE 0 END,
           falha = COALESCE(falha, 0) + CASE WHEN p_status = 'ERRO' THEN 1 ELSE 0 END
     WHERE id = p_batch_id;
    UPDATE public.execucoes_ai_batch
       SET status = CASE WHEN COALESCE(falha, 0) > 0 THEN 'ERRO' ELSE 'CONCLUIDO' END,
           finalizado_em = now()
     WHERE id = p_batch_id AND processados >= total;
    RETURN true;
END $$;

CREATE OR REPLACE FUNCTION public.finalizar_lote_ai_conta(
    p_batch_id uuid, p_account_key text, p_run_token uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_remaining integer; v_updated integer;
BEGIN
    SELECT count(*) INTO v_remaining FROM public.execucoes_ai_batch_pedido
     WHERE batch_id = p_batch_id AND account_key = p_account_key
       AND status IN ('PENDENTE', 'RODANDO');
    IF v_remaining > 0 THEN
        UPDATE public.execucoes_ai_batch_conta
           SET status = 'PENDENTE', run_token = NULL, lease_until = NULL,
               available_at = COALESCE((
                   SELECT min(i.available_at)
                     FROM public.execucoes_ai_batch_pedido i
                    WHERE i.batch_id = p_batch_id AND i.account_key = p_account_key
                      AND i.status = 'PENDENTE'
               ), now() + interval '30 seconds')
         WHERE batch_id = p_batch_id AND account_key = p_account_key
           AND status = 'RODANDO' AND run_token = p_run_token;
        RETURN false;
    END IF;
    UPDATE public.execucoes_ai_batch_conta
       SET status = CASE WHEN EXISTS (
              SELECT 1 FROM public.execucoes_ai_batch_pedido i
               WHERE i.batch_id = p_batch_id AND i.account_key = p_account_key
                 AND i.status = 'ERRO') THEN 'ERRO' ELSE 'CONCLUIDO' END,
           run_token = NULL, lease_until = NULL, finished_at = now()
     WHERE batch_id = p_batch_id AND account_key = p_account_key
       AND status = 'RODANDO' AND run_token = p_run_token;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated > 0;
END $$;

REVOKE ALL ON FUNCTION public.reivindicar_lote_ai_conta(uuid, text, uuid),
    public.renovar_lote_ai_conta(uuid, text, uuid),
    public.reivindicar_item_ai(uuid, text, bigint, uuid),
    public.adiar_item_ai(uuid, text, bigint, uuid, text, integer),
    public.concluir_item_ai(uuid, text, bigint, uuid, text, text, integer, text, jsonb, jsonb),
    public.finalizar_lote_ai_conta(uuid, text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reivindicar_lote_ai_conta(uuid, text, uuid),
    public.renovar_lote_ai_conta(uuid, text, uuid),
    public.reivindicar_item_ai(uuid, text, bigint, uuid),
    public.adiar_item_ai(uuid, text, bigint, uuid, text, integer),
    public.concluir_item_ai(uuid, text, bigint, uuid, text, text, integer, text, jsonb, jsonb),
    public.finalizar_lote_ai_conta(uuid, text, uuid) TO service_role;
