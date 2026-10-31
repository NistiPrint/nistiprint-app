BEGIN;
INSERT INTO pedidos(id,codigo_pedido_externo) VALUES(1101,'123'),(1102,'456'),(1103,'789'),(1104,'1000'),(1105,'2000');
ALTER TABLE gestao_financeiro DISABLE TRIGGER trg_gestao_ml_taxa_observada;
INSERT INTO gestao_financeiro(pedido_id,source,evidence,components) VALUES
 (1101,'ml_billing','{"total":1,"errors":[],"results":[{"order_id":123,"sale_fee":{"net":4.01}}]}','{"shipping":8}'),
 (1102,'ml_billing','{"total":1,"errors":[],"results":[{"order_id":999,"sale_fee":{"net":5}}]}','{}'),
 (1103,'ml_billing','{"total":2,"errors":[],"results":[{"order_id":789,"sale_fee":{"net":7}}]}','{}'),
 (1104,'ml_billing','{"total":2,"errors":[],"results":[{"order_id":1000,"sale_fee":{"net":2}},{"order_id":1001,"sale_fee":{"net":8}}]}','{}'),
 (1105,'ml_billing','{"total":2,"errors":[],"results":[{"order_id":2000,"sale_fee":{"net":2}},{"order_id":2000,"sale_fee":{"net":8}}]}','{}');
ALTER TABLE gestao_financeiro ENABLE TRIGGER trg_gestao_ml_taxa_observada;
DO $$ DECLARE r jsonb;
BEGIN
 r:=gestao_ml_taxa_venda_backfill(1100,10);
 IF (r->>'updated')::int<>2 THEN RAISE EXCEPTION 'unexpected update count %',r; END IF;
 IF (SELECT components FROM gestao_financeiro WHERE pedido_id=1101)<>'{"sale_fee":4.01,"shipping":8}'::jsonb THEN RAISE EXCEPTION 'wrong components'; END IF;
 IF (SELECT components FROM gestao_financeiro WHERE pedido_id=1102)<>'{}'::jsonb OR (SELECT components FROM gestao_financeiro WHERE pedido_id=1103)<>'{}'::jsonb THEN RAISE EXCEPTION 'ambiguous evidence accepted'; END IF;
 IF (SELECT components FROM gestao_financeiro WHERE pedido_id=1104)<>'{"sale_fee":2}'::jsonb OR (SELECT components FROM gestao_financeiro WHERE pedido_id=1105)<>'{}'::jsonb THEN RAISE EXCEPTION 'package matching wrong'; END IF;
 r:=gestao_ml_taxa_venda_backfill(1100,10);
 IF (r->>'updated')::int<>0 THEN RAISE EXCEPTION 'not idempotent'; END IF;
END $$;
ROLLBACK;
