BEGIN;
DO $$
DECLARE claim jsonb; ok boolean; observed jsonb;
BEGIN
 claim := marketplace_catalog_sync_claim(6);
 ok := marketplace_catalog_sync_store_page(6,(claim->>'owner_token')::uuid,
 '[{"item_externo_id":"observation-test","titulo":"Exemplo","dados_observados":{"description":"Detalhes","weight":"0.65"},"unidades":[{"variacao_externa_id":"1","dados_observados":{"gtin_code":"00","stock_info_v2":{"quantity":0}},"atributos_variacao":{"Cor":"Azul"}}]}]'::jsonb,'{}'::jsonb,true);
 IF NOT ok THEN RAISE EXCEPTION 'store failed'; END IF;
 SELECT dados_observados INTO observed FROM marketplace_anuncios WHERE integration_id=6 AND item_externo_id='observation-test';
 IF observed->>'description'<>'Detalhes' THEN RAISE EXCEPTION 'missing observed description'; END IF;
 SELECT dados_observados INTO observed FROM produto_anuncios WHERE integration_id=6 AND item_externo_id='observation-test';
 IF observed->>'gtin_code'<>'00' OR observed->'stock_info_v2'->>'quantity'<>'0' THEN RAISE EXCEPTION 'unit observations lost'; END IF;
 IF marketplace_catalog_sync_store_page(6,(claim->>'owner_token')::uuid,'[]','{}',true) THEN RAISE EXCEPTION 'expired lease accepted'; END IF;
END $$;
ROLLBACK;
