-- Preserve request priority and force intent at the smallest schedulable unit.
ALTER TABLE public.mercadolivre_personalization_batches
    ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'scheduled';
ALTER TABLE public.mercadolivre_personalization_batch_items
    ADD COLUMN IF NOT EXISTS force boolean NOT NULL DEFAULT false;

UPDATE public.mercadolivre_personalization_batches
   SET source = 'scheduled'
 WHERE source IS NULL OR source NOT IN ('manual', 'scheduled');

CREATE INDEX IF NOT EXISTS ix_ml_ai_ready_source
    ON public.mercadolivre_personalization_batches
       (marketplace_integration_id, status, available_at, source, created_at);

CREATE TABLE IF NOT EXISTS public.mercadolivre_personalization_batch_subscribers (
    batch_id uuid NOT NULL REFERENCES public.mercadolivre_personalization_batches(id) ON DELETE CASCADE,
    user_id integer NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, user_id)
);
ALTER TABLE public.mercadolivre_personalization_batch_subscribers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.mercadolivre_personalization_batch_subscribers FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.mercadolivre_personalization_batch_subscribers TO service_role;

CREATE OR REPLACE FUNCTION public.ml_ai_merge_manual_packs(
    p_integration_id integer,
    p_running_batch_id uuid,
    p_new_batch_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_active public.mercadolivre_personalization_batches;
    v_new public.mercadolivre_personalization_batches;
    v_added integer;
    v_forced integer := 0;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('ml-ai:' || p_integration_id::text, 0));
    SELECT * INTO v_active FROM public.mercadolivre_personalization_batches
     WHERE id = p_running_batch_id AND marketplace_integration_id = p_integration_id
       AND status = 'RUNNING' FOR UPDATE;
    SELECT * INTO v_new FROM public.mercadolivre_personalization_batches
     WHERE id = p_new_batch_id AND marketplace_integration_id = p_integration_id
       AND status = 'PENDING' FOR UPDATE;
    IF NOT FOUND OR v_active.id IS NULL THEN
        RETURN jsonb_build_object('merged', false);
    END IF;

    -- A force request for a pack already finished in this batch must remain
    -- a separate queued attempt; the current batch has one row per pack.
    IF EXISTS (
        SELECT 1 FROM public.mercadolivre_personalization_batch_items requested_item
        JOIN public.mercadolivre_personalization_batch_items active_item
          ON active_item.batch_id=p_running_batch_id AND active_item.pack_id=requested_item.pack_id
        WHERE requested_item.batch_id=p_new_batch_id AND requested_item.force IS TRUE
          AND active_item.status IN ('COMPLETED','FAILED')
    ) THEN
        RETURN jsonb_build_object('merged', false, 'reason', 'forced_item_already_finished');
    END IF;

    WITH inserted AS (
        INSERT INTO public.mercadolivre_personalization_batch_items
            (batch_id, marketplace_integration_id, pack_id, status, phase, force,
             next_attempt_at, pedido_ids)
        SELECT p_running_batch_id, i.marketplace_integration_id, i.pack_id,
               'PENDING', 'FIRST_PASS', i.force, now(), i.pedido_ids
          FROM public.mercadolivre_personalization_batch_items i
         WHERE i.batch_id = p_new_batch_id
        ON CONFLICT (batch_id, pack_id) DO NOTHING
        RETURNING pack_id
    ) SELECT count(*) INTO v_added FROM inserted;

    UPDATE public.mercadolivre_personalization_batch_items active_item
       SET force = true
      FROM public.mercadolivre_personalization_batch_items requested_item
     WHERE active_item.batch_id = p_running_batch_id
       AND requested_item.batch_id = p_new_batch_id
       AND requested_item.pack_id = active_item.pack_id
       AND requested_item.force IS TRUE
       AND active_item.status = 'PENDING'
       AND active_item.force IS FALSE;
    GET DIAGNOSTICS v_forced = ROW_COUNT;

    DELETE FROM public.mercadolivre_personalization_batches WHERE id = p_new_batch_id;
    IF v_added + v_forced > 0 THEN
        UPDATE public.mercadolivre_personalization_batches
           SET total = total + v_added,
               pack_ids = coalesce(pack_ids, '[]'::jsonb) || to_jsonb(
                   (SELECT coalesce(array_agg(i.pack_id), ARRAY[]::text[])
                      FROM public.mercadolivre_personalization_batch_items i
                     WHERE i.batch_id = p_running_batch_id)),
               source = 'manual', updated_at = now()
         WHERE id = p_running_batch_id;
    END IF;
    RETURN jsonb_build_object('merged', true, 'added', v_added + v_forced,
                              'batch_id', p_running_batch_id);
END $$;

REVOKE ALL ON FUNCTION public.ml_ai_merge_manual_packs(integer, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ml_ai_merge_manual_packs(integer, uuid, uuid) TO service_role;

CREATE OR REPLACE FUNCTION public.ml_ai_release_batch(p_batch_id uuid,p_token uuid)
RETURNS SETOF public.mercadolivre_personalization_batches
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.mercadolivre_personalization_batches; next_at timestamptz; next_phase text;
BEGIN
 SELECT * INTO b FROM public.mercadolivre_personalization_batches WHERE id=p_batch_id;
 IF NOT FOUND THEN RETURN; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ml-ai:'||b.marketplace_integration_id::text,0));
 SELECT * INTO b FROM public.mercadolivre_personalization_batches
  WHERE id=p_batch_id AND status='RUNNING' AND run_token=p_token FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 IF EXISTS (SELECT 1 FROM public.mercadolivre_personalization_batch_items
             WHERE batch_id=p_batch_id AND status='RUNNING') THEN
   UPDATE public.mercadolivre_personalization_batches
      SET lease_until=now(),available_at=now()+interval '30 seconds',updated_at=now()
    WHERE id=p_batch_id RETURNING * INTO b;
   RETURN NEXT b; RETURN;
 END IF;
 SELECT min(next_attempt_at) INTO next_at FROM public.mercadolivre_personalization_batch_items
  WHERE batch_id=p_batch_id AND status='PENDING' AND phase='FIRST_PASS';
 IF next_at IS NOT NULL THEN next_phase:='FIRST_PASS';
 ELSE
   SELECT min(next_attempt_at) INTO next_at FROM public.mercadolivre_personalization_batch_items
    WHERE batch_id=p_batch_id AND status='RETRY_PENDING';
   next_phase:='RETRY';
 END IF;
 UPDATE public.mercadolivre_personalization_batches
    SET status=CASE WHEN next_at IS NULL THEN 'COMPLETED' ELSE 'PENDING' END,updated_at=now(),
        phase=CASE WHEN next_at IS NULL THEN 'DONE' ELSE next_phase END,
        available_at=coalesce(next_at,now()),lease_until=NULL,run_token=NULL,
        finished_at=CASE WHEN next_at IS NULL THEN now() ELSE NULL END,
        error_message=CASE WHEN failed_count>0 THEN failed_count::text||' pacote(s) com falha definitiva.' ELSE NULL END
  WHERE id=p_batch_id RETURNING * INTO b;
 RETURN NEXT b;
END $$;

REVOKE ALL ON FUNCTION public.ml_ai_release_batch(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ml_ai_release_batch(uuid, uuid) TO service_role;
