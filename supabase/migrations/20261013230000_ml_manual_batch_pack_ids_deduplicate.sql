-- A manual request merged into a running batch must append only new packs.
-- The previous implementation rebuilt pack_ids from all active items and
-- appended that full list to the existing JSON array, duplicating old ids.
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

    IF EXISTS (
        SELECT 1 FROM public.mercadolivre_personalization_batch_items requested_item
        JOIN public.mercadolivre_personalization_batch_items active_item
          ON active_item.batch_id = p_running_batch_id
         AND active_item.pack_id = requested_item.pack_id
        WHERE requested_item.batch_id = p_new_batch_id
          AND requested_item.force IS TRUE
          AND active_item.status IN ('COMPLETED', 'FAILED')
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
        UPDATE public.mercadolivre_personalization_batches batch
           SET total = batch.total + v_added,
               pack_ids = (
                   SELECT coalesce(
                       jsonb_agg(to_jsonb(packs.pack_id) ORDER BY packs.first_order),
                       '[]'::jsonb
                   )
                     FROM (
                         SELECT merged.pack_id, min(merged.first_order) AS first_order
                           FROM (
                               SELECT old.pack_id, old.ordinality AS first_order
                                 FROM jsonb_array_elements_text(
                                     coalesce(v_active.pack_ids, '[]'::jsonb)
                                 ) WITH ORDINALITY AS old(pack_id, ordinality)
                               UNION ALL
                               SELECT item.pack_id,
                                      1000000 + row_number() OVER (ORDER BY item.pack_id)
                                 FROM public.mercadolivre_personalization_batch_items item
                                WHERE item.batch_id = p_running_batch_id
                           ) merged
                          GROUP BY merged.pack_id
                     ) packs
               ),
               source = 'manual', updated_at = now()
         WHERE batch.id = p_running_batch_id;
    END IF;
    RETURN jsonb_build_object('merged', true, 'added', v_added + v_forced,
                              'batch_id', p_running_batch_id);
END $$;

REVOKE ALL ON FUNCTION public.ml_ai_merge_manual_packs(integer, uuid, uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ml_ai_merge_manual_packs(integer, uuid, uuid)
    TO service_role;
