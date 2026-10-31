BEGIN;
INSERT INTO pedidos(id,codigo_pedido_externo) VALUES(1201,'123'),(1202,'456');
INSERT INTO gestao_financeiro(pedido_id,source,evidence,components) VALUES
 (1201,'ml_billing','{"total":2,"errors":[],"results":[{"order_id":123,"sale_fee":{"net":0}},{"order_id":456,"sale_fee":{"net":8}}]}','{"shipping":4}'),
 (1202,'manual','{"total":1,"errors":[],"results":[{"order_id":456,"sale_fee":{"net":8}}]}','{"sale_fee":9}');
DO $$ BEGIN
 IF (SELECT components FROM gestao_financeiro WHERE pedido_id=1201)<>'{"sale_fee":0,"shipping":4}'::jsonb THEN RAISE EXCEPTION 'zero or other component lost'; END IF;
 IF (SELECT components FROM gestao_financeiro WHERE pedido_id=1202)<>'{"sale_fee":9}'::jsonb THEN RAISE EXCEPTION 'manual overwritten'; END IF;
 UPDATE gestao_financeiro SET evidence='{"total":2,"errors":[],"results":[{"order_id":123,"sale_fee":{"net":2}}]}' WHERE pedido_id=1201;
 IF (SELECT components FROM gestao_financeiro WHERE pedido_id=1201)<>'{"shipping":4}'::jsonb THEN RAISE EXCEPTION 'partial evidence retained as current'; END IF;
END $$;
ROLLBACK;
