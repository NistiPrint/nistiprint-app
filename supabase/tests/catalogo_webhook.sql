BEGIN;
DO $$ DECLARE claim jsonb; start_scan timestamptz; start_item timestamptz; r text; ok boolean; existing jsonb;
BEGIN
 INSERT INTO public.marketplace_anuncios(integration_id,item_externo_id,titulo,collected_at)
 VALUES(6,'MLB990001','Original',clock_timestamp()-interval '1 hour'),(6,'MLB990002','Outro',clock_timestamp()-interval '1 hour');
 claim:=marketplace_catalog_sync_claim(6);
 start_scan:=clock_timestamp();
 start_item:=clock_timestamp();
 r:=marketplace_catalog_store_item(6,'{"item_externo_id":"MLB990001","titulo":"Novo","provider_updated_at":"2026-10-30T12:00:00Z","unidades":[{"variacao_externa_id":"1","sku_externo":"AAA","atributos_variacao":{"Cor":"Azul"},"preco_observado":"10"}]}'::jsonb,start_item);
 IF r<>'updated' THEN RAISE EXCEPTION 'targeted write failed: %',r; END IF;
 r:=marketplace_catalog_store_item(6,'{"item_externo_id":"MLB990001","titulo":"Antigo","unidades":[]}'::jsonb,start_scan-interval '1 second');
 IF r<>'stale' THEN RAISE EXCEPTION 'stale targeted write accepted'; END IF;
 ok:=marketplace_catalog_sync_store_page(6,(claim->>'owner_token')::uuid,
  jsonb_build_array(jsonb_build_object('item_externo_id','MLB990001','titulo','Antigo','observed_at',start_scan,'unidades','[]'::jsonb),
   jsonb_build_object('item_externo_id','MLB990002','titulo','Outro','observed_at',start_scan,'unidades','[]'::jsonb)),'{}',true);
 IF NOT ok THEN RAISE EXCEPTION 'scan failed'; END IF;
 SELECT to_jsonb(a) INTO existing FROM public.marketplace_anuncios a WHERE integration_id=6 AND item_externo_id='MLB990001';
 IF existing->>'titulo'<>'Novo' OR existing->>'absent_since' IS NOT NULL THEN RAISE EXCEPTION 'stale scan overwrote or removed new observation: %',existing; END IF;
 IF NOT EXISTS(SELECT 1 FROM produto_anuncios WHERE integration_id=6 AND item_externo_id='MLB990001' AND sku_externo='AAA') THEN RAISE EXCEPTION 'unit lost'; END IF;
END $$;
DO $$ DECLARE claim jsonb; scan_started timestamptz:=clock_timestamp()-interval '3 seconds';
 item_started timestamptz:=clock_timestamp()-interval '2 seconds'; ok boolean; r text;
BEGIN
 INSERT INTO marketplace_anuncios(integration_id,item_externo_id,titulo,collected_at) VALUES(6,'MLB990003','Original',clock_timestamp()-interval '1 hour');
 claim:=marketplace_catalog_sync_claim(6);
 ok:=marketplace_catalog_sync_store_page(6,(claim->>'owner_token')::uuid,
  jsonb_build_array(jsonb_build_object('item_externo_id','MLB990003','titulo','Consulta antiga','observed_at',scan_started,'unidades','[]'::jsonb)),'{}',false);
 IF NOT ok THEN RAISE EXCEPTION 'scan failed'; END IF;
 r:=marketplace_catalog_store_item(6,'{"item_externo_id":"MLB990003","titulo":"Consulta nova","unidades":[]}'::jsonb,item_started);
 IF r<>'updated' OR (SELECT titulo FROM marketplace_anuncios WHERE integration_id=6 AND item_externo_id='MLB990003')<>'Consulta nova' THEN
  RAISE EXCEPTION 'newer request rejected when older scan stored later: %',r;
 END IF;
END $$;
ROLLBACK;
