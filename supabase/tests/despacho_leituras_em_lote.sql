INSERT INTO installed_integrations(id,module_id,instance_name) VALUES (6,'shopee','Shopee'),(9,'mercadolivre','ML');
INSERT INTO modalidades_logisticas(id,module_id,codigo,nome,tipo_prazo,offset_etiqueta_min,offset_coleta_min)
 VALUES(1,'shopee','COMUM','Comum','FIXO',NULL,NULL),(2,'mercadolivre','COMUM','Comum ML','FIXO',NULL,NULL),
       (3,'shopee','TURBO','Turbo','RELATIVO',40,60);
INSERT INTO regras_logisticas_integracao(marketplace_integration_id,modalidade,tipo_envio,
 horario_corte,horario_coleta,horario_limite,modalidade_id)
 VALUES(6,'STANDARD','COLETA_LOCAL','13:00','17:00','17:00',1),
       (9,'STANDARD','COLETA_LOCAL','13:00','17:00','17:00',2);
INSERT INTO regra_logistica_modalidades SELECT id,modalidade_id,now() FROM regras_logisticas_integracao;

-- Varios pedidos, referencias distintas e prazos antes/depois do corte.
INSERT INTO pedidos(id,numero_pedido,marketplace_module_id,marketplace_integration_id,
 modalidade_logistica_id,situacao_pedido_id,data_pagamento_marketplace,data_limite_envio)
SELECT n,n::text,CASE WHEN n%2=0 THEN 'mercadolivre' ELSE 'shopee' END,
 CASE WHEN n%2=0 THEN 9 ELSE 6 END,CASE WHEN n%2=0 THEN 2 ELSE 1 END,
 2,'2026-10-02T08:00:00-03:00'::timestamptz + n*interval '1 minute',
 '2026-10-02T23:59:59-03:00'::timestamptz + (n%7)*interval '1 day'
FROM generate_series(1,300) n;
INSERT INTO itens_pedido(pedido_id,quantidade) SELECT id,2 FROM pedidos;
INSERT INTO pedidos(id,numero_pedido,marketplace_module_id,marketplace_integration_id,modalidade_logistica_id,
 situacao_pedido_id,compromisso_logistico_em)
VALUES(301,'301','shopee',6,3,2,'2026-10-02T10:00:00-03:00'),(302,'302','shopee',6,NULL,2,NULL),
 (303,'303','shopee',6,1,4,NULL),(304,'304','shopee',6,1,3,NULL);
UPDATE pedidos SET situacao_pedido_id=4,marketplace_shipping_substatus='ready_to_print'
 WHERE id=2;

DO $$
DECLARE instante timestamptz; falhas integer; ctx jsonb;
BEGIN
 FOREACH instante IN ARRAY ARRAY['2026-10-02T09:00:00-03:00'::timestamptz,
     '2026-10-02T14:00:00-03:00'::timestamptz,'2026-10-02T19:00:00-03:00'::timestamptz] LOOP
   SELECT count(*) INTO falhas FROM pedidos p
    LEFT JOIN LATERAL despacho_coleta_do_pedido(p.marketplace_module_id,p.modalidade_logistica_id,
       p.marketplace_integration_id,p.data_pagamento_marketplace,p.data_limite_envio,instante) antigo ON true
    LEFT JOIN despacho_coletas_em_lote(ARRAY(SELECT id FROM pedidos),instante) novo ON novo.pedido_id=p.id
    WHERE ROW(antigo.corte_em,antigo.coleta_em,antigo.prazo_final_em)
      IS DISTINCT FROM ROW(novo.corte_em,novo.coleta_em,novo.prazo_final_em);
   IF falhas>0 THEN RAISE EXCEPTION 'Coleta em lote divergiu em % pedidos, horario %',falhas,instante; END IF;
 END LOOP;
 ctx:=despacho_escopo_contexto(6,ARRAY[1],ARRAY['amanha'],'2026-10-02');
 IF jsonb_array_length(ctx->'pedido_ids')<>(ctx->'buckets'->>'amanha')::integer
    OR jsonb_array_length(ctx->'pedidos')<>jsonb_array_length(ctx->'pedido_ids') THEN
   RAISE EXCEPTION 'Card, escopo e pedidos divergem';
 END IF;
 IF (SELECT count(*) FROM vw_pedidos_pendentes_despacho WHERE id IN (303,304))<>2 THEN
   RAISE EXCEPTION 'Torre omitiu pedidos ainda elegiveis nas situacoes 3/4';
 END IF;
 IF EXISTS(SELECT 1 FROM vw_pedidos_pendentes_despacho WHERE id=2) THEN
   RAISE EXCEPTION 'Pedido ML com etiqueta pronta permaneceu na torre';
 END IF;
 UPDATE pedidos SET marketplace_shipping_substatus='printed' WHERE id=2;
 IF EXISTS(SELECT 1 FROM vw_pedidos_pendentes_despacho WHERE id=2) THEN
   RAISE EXCEPTION 'Pedido ML com etiqueta impressa permaneceu na torre';
 END IF;
 UPDATE pedidos SET marketplace_shipping_substatus='invoice_pending' WHERE id=2;
 IF EXISTS(SELECT 1 FROM vw_pedidos_pendentes_despacho WHERE id=2) THEN
   RAISE EXCEPTION 'Regressao do substatus fiscal devolveu pedido 4 para a torre';
 END IF;
 IF EXISTS(
   SELECT 1 FROM integration_status_mappings
    WHERE module_id='mercadolivre' AND integration_id IS NULL
      AND status_domain='shipping_substatus'
      AND external_status_id IN ('ready_to_print','printed')
      AND lifecycle_stage <> 'fulfillment_ready'
 ) OR (
   SELECT count(*) FROM integration_status_mappings
    WHERE module_id='mercadolivre' AND integration_id IS NULL
      AND status_domain='shipping_substatus'
      AND external_status_id IN ('ready_to_print','printed')
 ) <> 2 THEN
   RAISE EXCEPTION 'Mapeamento de etiqueta Mercado Livre ausente ou incorreto';
 END IF;
 IF (SELECT sum(qtd_pedidos) FROM despacho_arvore('2026-10-02') WHERE nivel=0)<>303 THEN
   RAISE EXCEPTION 'Arvore omitiu ou duplicou pedidos';
 END IF;
 IF jsonb_array_length(despacho_arvore_contexto('2026-10-02')->'rows')=0 THEN
   RAISE EXCEPTION 'Contexto da torre vazio';
 END IF;
END $$;

-- O recorte grande nao fica limitado as 1000 linhas do PostgREST.
SELECT setval(pg_get_serial_sequence('pedidos','id'),max(id)) FROM pedidos;
INSERT INTO pedidos(numero_pedido,situacao_pedido_id)
 SELECT 'bulk-'||n,2 FROM generate_series(1,1200) n;
DO $$ BEGIN
 IF jsonb_array_length(despacho_ler_pedidos(ARRAY(SELECT id FROM pedidos)))<>1504
 THEN RAISE EXCEPTION 'Leitura de pedidos truncada'; END IF;
END $$;

-- Pedido real do recorte, com dados sinteticos: a origem da correcao e auditavel.
UPDATE pedidos SET marketplace_order_id='261005T9TABWHR',data_limite_envio='2026-10-07T23:59:59-03:00' WHERE id=1;
INSERT INTO pedidos_shopee(codigo_pedido,ship_by_date) VALUES('261005T9TABWHR',NULL);
INSERT INTO pedido_snapshots(pedido_id) VALUES(1);
-- Estimativa antiga sem prazo oficial, para testar a volta ao fallback de coleta.
UPDATE pedidos SET marketplace_order_id='sem-api-estimado',data_limite_envio=
    (((data_pagamento_marketplace AT TIME ZONE 'America/Sao_Paulo')::date + 3)::timestamp
      AT TIME ZONE 'America/Sao_Paulo')-interval '1 second' WHERE id=3;
INSERT INTO pedidos_shopee(codigo_pedido,ship_by_date,dias_para_envio) VALUES('sem-api-estimado',NULL,2);
INSERT INTO pedido_snapshots(pedido_id) VALUES(3);
