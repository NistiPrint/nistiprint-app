-- Idempotent, context-checked restoration from an existing AI execution log.
CREATE OR REPLACE FUNCTION public.restore_mercadolivre_personalizations_from_log(
  p_integration_id integer,
  p_pack_id text,
  p_log_id bigint,
  p_context_hash text,
  p_records jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_source mercadolivre_personalization_logs%ROWTYPE;
  v_record jsonb;
  v_rows integer := 0;
  v_pedido_id integer;
  v_item_id integer;
BEGIN
  SELECT * INTO v_source FROM mercadolivre_personalization_logs
   WHERE id = p_log_id AND marketplace_integration_id = p_integration_id
     AND pack_id = p_pack_id AND status = 'success';
  IF NOT FOUND THEN RAISE EXCEPTION 'source AI log is missing or not successful'; END IF;
  IF jsonb_typeof(p_records) <> 'array' OR jsonb_array_length(p_records) = 0 THEN
    RAISE EXCEPTION 'recovery records must be a nonempty array';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM mercadolivre_chat_conversations c
     WHERE c.marketplace_integration_id = p_integration_id AND c.pack_id = p_pack_id
       AND c.context_hash = p_context_hash
  ) THEN RAISE EXCEPTION 'current conversation context changed since AI execution'; END IF;

  FOR v_record IN SELECT value FROM jsonb_array_elements(p_records) LOOP
    v_pedido_id := (v_record->>'pedido_id')::integer;
    v_item_id := (v_record->>'item_pedido_id')::integer;
    IF NOT EXISTS (
      SELECT 1 FROM pedidos p JOIN itens_pedido i ON i.id = v_item_id AND i.pedido_id = p.id
       WHERE p.id = v_pedido_id AND p.marketplace_integration_id = p_integration_id
         AND p.marketplace_module_id = 'mercadolivre'
    ) THEN RAISE EXCEPTION 'recovery item/order is outside Mercado Livre integration'; END IF;

    -- Never overwrite a human confirmation. The stable provider_item_id makes
    -- retries idempotent under the existing uniqueness constraint.
    IF NOT EXISTS (
      SELECT 1 FROM mercadolivre_personalizations p
       WHERE p.marketplace_integration_id = p_integration_id AND p.pedido_id = v_pedido_id
         AND p.item_pedido_id = v_item_id AND (p.confirmed = TRUE OR p.source = 'manual')
    ) THEN
      INSERT INTO mercadolivre_personalizations (
        marketplace_integration_id, pedido_id, item_pedido_id, pack_id,
        provider_order_id, provider_item_id, provider_message_id,
        quantity_to_personalize, customization_name, customization_initial,
        status, reasoning, context_hash, source, confirmed, details, created_at, updated_at
      ) VALUES (
        p_integration_id, v_pedido_id, v_item_id, p_pack_id,
        v_record->>'provider_order_id', v_record->>'provider_item_id',
        v_record->>'provider_message_id', (v_record->>'quantity_to_personalize')::integer,
        NULLIF(v_record->>'customization_name', ''), NULLIF(v_record->>'customization_initial', ''),
        'SUCCESS', v_record->>'reasoning', p_context_hash, 'ai', FALSE,
        COALESCE(v_record->'details', '{}'::jsonb) || jsonb_build_object('restored_from_log_id', p_log_id),
        v_source.executed_at, v_source.executed_at
      ) ON CONFLICT (marketplace_integration_id, pedido_id, item_pedido_id, provider_item_id, context_hash)
        DO NOTHING;
      IF FOUND THEN v_rows := v_rows + 1; END IF;
    END IF;
  END LOOP;

  IF NOT EXISTS (
    SELECT 1 FROM mercadolivre_personalization_logs l
     WHERE l.marketplace_integration_id = p_integration_id AND l.pack_id = p_pack_id
       AND l.status = 'recovered' AND l.metadata->>'restored_from_log_id' = p_log_id::text
  ) THEN
    INSERT INTO mercadolivre_personalization_logs (
      marketplace_integration_id, pack_id, status, input_data, model_result, metadata, executed_at
    ) VALUES (
      p_integration_id, p_pack_id, 'recovered', v_source.input_data, v_source.model_result,
      COALESCE(v_source.metadata, '{}'::jsonb) || jsonb_build_object('restored_from_log_id', p_log_id),
      v_source.executed_at
    );
  END IF;
  RETURN jsonb_build_object('saved', v_rows, 'source_log_id', p_log_id,
                            'source_executed_at', v_source.executed_at);
END;
$$;

REVOKE ALL ON FUNCTION public.restore_mercadolivre_personalizations_from_log(integer, text, bigint, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.restore_mercadolivre_personalizations_from_log(integer, text, bigint, text, jsonb) TO service_role;
