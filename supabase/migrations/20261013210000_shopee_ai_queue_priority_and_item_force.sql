ALTER TABLE public.execucoes_ai_batch
    ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'scheduled';
ALTER TABLE public.execucoes_ai_batch_conta
    ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'scheduled';
ALTER TABLE public.execucoes_ai_batch_pedido
    ADD COLUMN IF NOT EXISTS force boolean NOT NULL DEFAULT false;

UPDATE public.execucoes_ai_batch_pedido item
   SET force = batch.force
  FROM public.execucoes_ai_batch batch
 WHERE item.batch_id = batch.id
   AND batch.force IS TRUE
   AND item.force IS FALSE;

CREATE TABLE IF NOT EXISTS public.execucoes_ai_batch_subscribers (
    batch_id uuid NOT NULL REFERENCES public.execucoes_ai_batch(id) ON DELETE CASCADE,
    user_id integer NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, user_id)
);
ALTER TABLE public.execucoes_ai_batch_subscribers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.execucoes_ai_batch_subscribers FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.execucoes_ai_batch_subscribers TO service_role;

CREATE OR REPLACE FUNCTION public.ai_merge_manual_account_orders(
    p_account_key text, p_active_batch_id uuid, p_new_batch_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_active public.execucoes_ai_batch_conta;
    v_new public.execucoes_ai_batch_conta;
    v_added integer;
    v_forced integer := 0;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('shopee-ai:' || p_account_key, 0));
    SELECT * INTO v_active FROM public.execucoes_ai_batch_conta
     WHERE batch_id=p_active_batch_id AND account_key=p_account_key AND status='RODANDO' FOR UPDATE;
    SELECT * INTO v_new FROM public.execucoes_ai_batch_conta
     WHERE batch_id=p_new_batch_id AND account_key=p_account_key AND status='PENDENTE' FOR UPDATE;
    IF NOT FOUND OR v_active.batch_id IS NULL THEN
        RETURN jsonb_build_object('merged',false);
    END IF;

    -- Keep a forced reprocess as a new attempt when this execution already
    -- completed that order; its current batch has a unique row per order.
    IF EXISTS (
        SELECT 1 FROM public.execucoes_ai_batch_pedido requested_item
        JOIN public.execucoes_ai_batch_pedido active_item
          ON active_item.batch_id=p_active_batch_id AND active_item.pedido_id=requested_item.pedido_id
         AND active_item.account_key=p_account_key
        WHERE requested_item.batch_id=p_new_batch_id AND requested_item.account_key=p_account_key
          AND requested_item.force IS TRUE
          AND active_item.status NOT IN ('PENDENTE','RODANDO')
    ) THEN
        RETURN jsonb_build_object('merged',false,'reason','forced_item_already_finished');
    END IF;

    WITH inserted AS (
        INSERT INTO public.execucoes_ai_batch_pedido(batch_id,account_key,pedido_id,status,force,available_at)
        SELECT p_active_batch_id,p_account_key,i.pedido_id,'PENDENTE',i.force,now()
          FROM public.execucoes_ai_batch_pedido i
         WHERE i.batch_id=p_new_batch_id AND i.account_key=p_account_key
        ON CONFLICT(batch_id,pedido_id) DO NOTHING
        RETURNING pedido_id
    ) SELECT count(*) INTO v_added FROM inserted;

    UPDATE public.execucoes_ai_batch_pedido active_item
       SET force=true
      FROM public.execucoes_ai_batch_pedido requested_item
     WHERE active_item.batch_id=p_active_batch_id AND active_item.account_key=p_account_key
       AND requested_item.batch_id=p_new_batch_id AND requested_item.account_key=p_account_key
       AND requested_item.pedido_id=active_item.pedido_id AND requested_item.force
       AND active_item.status='PENDENTE' AND NOT active_item.force;
    GET DIAGNOSTICS v_forced = ROW_COUNT;

    UPDATE public.execucoes_ai_batch_conta
       SET pedido_ids=ARRAY(SELECT DISTINCT value FROM unnest(pedido_ids || v_new.pedido_ids) value),
           source='manual'
     WHERE batch_id=p_active_batch_id AND account_key=p_account_key;
    UPDATE public.execucoes_ai_batch
       SET pedido_ids=ARRAY(SELECT DISTINCT value FROM unnest(pedido_ids || v_new.pedido_ids) value),
           total=total+v_added,source='manual'
     WHERE id=p_active_batch_id;

    DELETE FROM public.execucoes_ai_batch_conta
     WHERE batch_id=p_new_batch_id AND account_key=p_account_key;
    IF NOT EXISTS (SELECT 1 FROM public.execucoes_ai_batch_conta WHERE batch_id=p_new_batch_id) THEN
        DELETE FROM public.execucoes_ai_batch WHERE id=p_new_batch_id;
    END IF;
    RETURN jsonb_build_object('merged',true,'added',v_added+v_forced,'batch_id',p_active_batch_id);
END $$;

REVOKE ALL ON FUNCTION public.ai_merge_manual_account_orders(text, uuid, uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ai_merge_manual_account_orders(text, uuid, uuid)
    TO service_role;

CREATE OR REPLACE FUNCTION public.finalizar_lote_ai_conta(
    p_batch_id uuid, p_account_key text, p_run_token uuid
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_remaining integer; v_updated integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('shopee-ai:' || p_account_key, 0));
    SELECT count(*) INTO v_remaining FROM public.execucoes_ai_batch_pedido
     WHERE batch_id = p_batch_id AND account_key = p_account_key
       AND status IN ('PENDENTE', 'RODANDO');
    IF v_remaining > 0 THEN
        UPDATE public.execucoes_ai_batch_conta
           SET status = 'PENDENTE', run_token = NULL, lease_until = NULL,
               available_at = COALESCE((
                   SELECT min(i.available_at) FROM public.execucoes_ai_batch_pedido i
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

REVOKE ALL ON FUNCTION public.finalizar_lote_ai_conta(uuid, text, uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalizar_lote_ai_conta(uuid, text, uuid)
    TO service_role;
