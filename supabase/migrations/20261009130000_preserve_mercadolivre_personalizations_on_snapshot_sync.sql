-- Preserve canonical item IDs for Mercado Livre orders. AI results reference
-- itens_pedido.id, so replacing rows cascades away the extracted names.
CREATE OR REPLACE FUNCTION public.sync_marketplace_snapshot_items()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_source text := lower(COALESCE(NEW.identity->>'ingest_source', ''));
  v_item jsonb;
  v_raw jsonb;
  v_sku text;
  v_title text;
  v_external_item_id text;
  v_variation_id text;
  v_quantity numeric;
  v_price numeric;
  v_subtotal numeric;
  v_item_id integer;
  v_match_count integer;
  v_matched_ids integer[] := ARRAY[]::integer[];
BEGIN
  IF v_source NOT IN ('shopee', 'mercadolivre')
     OR jsonb_typeof(NEW.items) <> 'array'
     OR jsonb_array_length(NEW.items) = 0 THEN
    RETURN NEW;
  END IF;

  IF v_source = 'mercadolivre' THEN
    -- First match on Mercado Livre listing + variation identity. Old snapshots
    -- without those IDs may use SKU + title only when that match is unique.
    FOR v_item IN SELECT value FROM jsonb_array_elements(NEW.items) LOOP
      v_raw := COALESCE(v_item->'raw'->'item', v_item->'item', '{}'::jsonb);
      v_sku := COALESCE(NULLIF(v_item->>'sku', ''), NULLIF(v_item->>'sku_externo', ''));
      v_title := COALESCE(NULLIF(v_item->>'name', ''), NULLIF(v_item->>'descricao', ''));
      v_external_item_id := COALESCE(NULLIF(v_raw->>'id', ''), NULLIF(v_item->>'item_externo_id', ''));
      v_variation_id := COALESCE(NULLIF(v_raw->>'variation_id', ''), NULLIF(v_item->>'variacao_externa_id', ''));
      v_quantity := COALESCE(NULLIF(v_item->>'quantity', '')::numeric,
                             NULLIF(v_item->>'quantidade', '')::numeric, 1);
      v_price := COALESCE(NULLIF(v_item->>'unit_price', '')::numeric,
                          NULLIF(v_item->>'preco_unitario', '')::numeric,
                          NULLIF(v_item->>'price', '')::numeric, 0);
      v_subtotal := COALESCE(NULLIF(v_item->>'subtotal', '')::numeric, v_quantity * v_price);
      v_item_id := NULL;

      IF v_external_item_id IS NOT NULL THEN
        SELECT count(*), min(i.id) INTO v_match_count, v_item_id
          FROM public.itens_pedido i
         WHERE i.pedido_id = NEW.pedido_id
           AND i.item_externo_id = v_external_item_id
           AND COALESCE(i.variacao_externa_id, '') = COALESCE(v_variation_id, '')
           AND NOT (i.id = ANY(v_matched_ids));
      ELSE
        SELECT count(*), min(i.id) INTO v_match_count, v_item_id
          FROM public.itens_pedido i
         WHERE i.pedido_id = NEW.pedido_id
           AND i.sku_externo = v_sku AND i.descricao = v_title
           AND NOT (i.id = ANY(v_matched_ids));
      END IF;

      IF v_match_count > 1 THEN
        RAISE EXCEPTION 'Ambiguous Mercado Livre item match for pedido_id %, listing %, variation %, SKU %',
          NEW.pedido_id, v_external_item_id, v_variation_id, v_sku
          USING ERRCODE = '21000';
      ELSIF v_match_count = 0 AND v_external_item_id IS NOT NULL AND v_sku IS NOT NULL THEN
        -- Legacy rows may not have listing IDs yet; permit their unique SKU/title match.
        SELECT count(*), min(i.id) INTO v_match_count, v_item_id
          FROM public.itens_pedido i
         WHERE i.pedido_id = NEW.pedido_id AND i.sku_externo = v_sku
           AND i.descricao = v_title AND NOT (i.id = ANY(v_matched_ids));
        IF v_match_count > 1 THEN
          RAISE EXCEPTION 'Ambiguous legacy Mercado Livre item match for pedido_id %, SKU %, title %',
            NEW.pedido_id, v_sku, v_title USING ERRCODE = '21000';
        END IF;
      END IF;

      IF v_match_count = 1 THEN
        UPDATE public.itens_pedido
           SET sku_externo = v_sku, descricao = v_title, quantidade = v_quantity,
               preco_unitario = v_price, subtotal = v_subtotal,
               item_externo_id = COALESCE(v_external_item_id, item_externo_id),
               variacao_externa_id = COALESCE(v_variation_id, variacao_externa_id),
               titulo_anuncio = COALESCE(v_title, titulo_anuncio), updated_at = now()
         WHERE id = v_item_id;
      ELSE
        INSERT INTO public.itens_pedido (
          pedido_id, sku_externo, descricao, quantidade, preco_unitario, subtotal,
          item_externo_id, variacao_externa_id, titulo_anuncio, created_at, updated_at
        ) VALUES (
          NEW.pedido_id, v_sku, v_title, v_quantity, v_price, v_subtotal,
          v_external_item_id, v_variation_id, v_title, now(), now()
        ) RETURNING id INTO v_item_id;
      END IF;
      v_matched_ids := array_append(v_matched_ids, v_item_id);
    END LOOP;

    -- The snapshot is complete; rows omitted from it are genuinely removed.
    DELETE FROM public.itens_pedido
     WHERE pedido_id = NEW.pedido_id AND NOT (id = ANY(v_matched_ids));
    RETURN NEW;
  END IF;

  -- Preserve the existing Shopee behavior.
  DELETE FROM public.itens_pedido WHERE pedido_id = NEW.pedido_id;
  INSERT INTO public.itens_pedido (
    pedido_id, produto_id, sku_externo, descricao, quantidade,
    preco_unitario, subtotal, created_at, updated_at
  )
  SELECT NEW.pedido_id,
    COALESCE(NULLIF(item->>'produto_id', '')::integer,
      (SELECT vb.produto_id FROM public.vinculos_bling vb
       WHERE vb.codigo_bling = COALESCE(item->>'sku', item->>'sku_externo') LIMIT 1),
      (SELECT p.id FROM public.produtos p
       WHERE p.sku = COALESCE(item->>'sku', item->>'sku_externo') LIMIT 1)),
    COALESCE(item->>'sku', item->>'sku_externo'),
    COALESCE(item->>'name', item->>'descricao'),
    COALESCE(NULLIF(item->>'quantity', '')::numeric, NULLIF(item->>'quantidade', '')::numeric, 1),
    COALESCE(NULLIF(item->>'unit_price', '')::numeric, NULLIF(item->>'preco_unitario', '')::numeric, NULLIF(item->>'price', '')::numeric, 0),
    COALESCE(NULLIF(item->>'subtotal', '')::numeric,
      COALESCE(NULLIF(item->>'quantity', '')::numeric, NULLIF(item->>'quantidade', '')::numeric, 1)
      * COALESCE(NULLIF(item->>'unit_price', '')::numeric, NULLIF(item->>'preco_unitario', '')::numeric, NULLIF(item->>'price', '')::numeric, 0)),
    now(), now()
  FROM jsonb_array_elements(NEW.items) AS item;
  RETURN NEW;
END;
$$;
