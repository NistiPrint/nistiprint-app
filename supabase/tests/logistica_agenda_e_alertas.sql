-- Executar em banco de testes apos as duas migrations. Nao usa clientes reais.
BEGIN;
CREATE FUNCTION pg_temp.assert_true(ok boolean,msg text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'Falhou: %',msg; END IF; END $$;
DO $test$
DECLARE iid integer; iid2 integer; mid integer; especifica integer; rid bigint; rid2 bigint;
 j record; pedido integer; semchave integer; desconhecido integer; demanda integer; n integer; v jsonb; horario timestamptz;
BEGIN
 INSERT INTO installed_integrations(module_id,instance_name) VALUES('mercadolivre','Teste ML') RETURNING id INTO iid;
 INSERT INTO installed_integrations(module_id,instance_name) VALUES('mercadolivre','Outra conta ML') RETURNING id INTO iid2;
 v:=logistica_salvar_modalidade(NULL,'{"module_id":"mercadolivre","codigo":"TESTE","nome":"Coleta","tipo_prazo":"FIXO"}','teste'); mid:=(v->>'id')::int;
 v:=logistica_salvar_modalidade(NULL,'{"module_id":"mercadolivre","codigo":"ESPECIFICA","nome":"Expressa","tipo_prazo":"FIXO"}','teste'); especifica:=(v->>'id')::int;
 v:=logistica_salvar_regra(NULL,jsonb_build_object('marketplace_integration_id',iid,'modalidade_id',mid,'tipo_envio','COLETA_LOCAL','horario_corte','13:00','horario_coleta','14:00','dias_semana',ARRAY[1,2,3,4,5,6,7]),'teste'); rid:=(v->>'id')::bigint;
 PERFORM logistica_salvar_regra(rid,'{"ativo":false}','teste');
 PERFORM pg_temp.assert_true((SELECT horario_corte='13:00' AND horario_coleta='14:00' FROM regras_logisticas_integracao WHERE id=rid),'edicao parcial conserva os horarios');
 PERFORM logistica_salvar_regra(rid,'{"ativo":true}','teste');
 SELECT * INTO j FROM coleta_do_pedido(mid,iid,'2026-10-02 13:00-03','2026-10-02 12:00-03');
 PERFORM pg_temp.assert_true(j.coleta_em='2026-10-02 14:00-03'::timestamptz,'pagamento exatamente no corte pertence ao lote');
 SELECT * INTO j FROM coleta_do_pedido(mid,iid,'2026-10-02 13:00:00.001-03','2026-10-02 12:00-03');
 PERFORM pg_temp.assert_true(j.coleta_em='2026-10-03 14:00-03'::timestamptz,'pagamento apos corte vai para proximo lote');
 v:=logistica_salvar_regra(NULL,jsonb_build_object('marketplace_integration_id',iid,'modalidade_id',mid,'tipo_envio','COLETA_LOCAL','horario_corte','13:00','horario_coleta','17:00','dias_semana',ARRAY[1,2,3,4,5,6,7]),'teste'); rid2:=(v->>'id')::bigint;
 SELECT * INTO j FROM coleta_do_pedido(mid,iid,'2026-10-02 13:00-03','2026-10-02 12:00-03');
 PERFORM pg_temp.assert_true(j.coleta_em='2026-10-02 14:00-03'::timestamptz AND j.prazo_final_em='2026-10-02 17:00-03'::timestamptz,'duas saidas no mesmo corte formam um lote');
 PERFORM logistica_salvar_regra(rid2,'{"horario_corte":"16:00"}','teste');
 SELECT count(*) INTO n FROM logistica_lotes(mid,iid,'2026-10-02','2026-10-02');
 PERFORM pg_temp.assert_true(n=2,'cortes distintos formam lotes distintos');
 PERFORM logistica_salvar_regra(rid2,'{"ativo":false}','teste');
 PERFORM logistica_salvar_regra(rid,'{"fonte_agenda":"MARKETPLACE","modo_corte":"ANTES_COLETA","antecedencia_corte_min":60,"logistic_type":"cross_docking"}','teste');
 INSERT INTO logistica_agendas(integration_id,logistic_type,agenda,consultada_em) VALUES(iid,'cross_docking',
 '{"friday":{"work":true,"detail":[{"from":"14:00","to":"15:00","cutoff":"12:30"},{"from":"19:00","to":"20:00","cutoff":"17:30"}]},"saturday":{"work":false,"detail":[]}}',now());
 SELECT * INTO j FROM logistica_janelas_efetivas(rid,'2026-10-02') ORDER BY coleta_em LIMIT 1;
 PERFORM pg_temp.assert_true(j.corte_em='2026-10-02 13:00-03'::timestamptz AND j.fonte='MARKETPLACE','corte relativo ao inicio da faixa');
 PERFORM pg_temp.assert_true((SELECT count(*)=2 FROM logistica_janelas_efetivas(rid,'2026-10-02')),'preserva varias faixas');
 PERFORM pg_temp.assert_true((SELECT count(*)=0 FROM logistica_janelas_efetivas(rid,'2026-10-03')),'sem atendimento nao usa contingencia');
 PERFORM pg_temp.assert_true((SELECT fonte='CONTINGENCIA' FROM logistica_janelas_efetivas(rid,'2026-10-04')),'dia ausente usa contingencia');
 PERFORM logistica_salvar_regra(rid,'{"modo_corte":"MARKETPLACE"}','teste');
 SELECT * INTO j FROM logistica_janelas_efetivas(rid,'2026-10-02') ORDER BY coleta_em LIMIT 1;
 PERFORM pg_temp.assert_true(j.corte_em='2026-10-02 12:30-03'::timestamptz,'corte oficial da agenda');
 UPDATE logistica_agendas SET consultada_em=now()-interval '31 minutes',erro='Falha temporaria' WHERE integration_id=iid;
 PERFORM pg_temp.assert_true((SELECT bool_and(desatualizada) FROM logistica_janelas_efetivas(rid,'2026-10-02')),'cache antigo continua visivel com aviso');
 PERFORM logistica_salvar_excecao(rid,'2026-10-02','{"janelas":[],"motivo":"Feriado"}','teste');
 PERFORM pg_temp.assert_true((SELECT count(*)=0 FROM logistica_janelas_efetivas(rid,'2026-10-02')),'excecao sem coleta precede agenda');
 PERFORM logistica_salvar_excecao(rid,'2026-10-02','{"janelas":[{"from":"00:30","cutoff":"23:30"}],"motivo":"Coleta noturna"}','teste');
 SELECT * INTO j FROM logistica_janelas_efetivas(rid,'2026-10-02');
 PERFORM pg_temp.assert_true(j.coleta_em='2026-10-02 00:30-03'::timestamptz AND j.corte_em='2026-10-01 23:30-03'::timestamptz,'virada de dia no fuso local');
 PERFORM logistica_salvar_excecao(rid,'2026-10-02',NULL,'teste');
 PERFORM logistica_salvar_regra(rid,'{"modo_corte":"FIXO","fonte_agenda":"MANUAL","horario_corte":"23:00","horario_coleta":"02:00"}','teste');
 SELECT * INTO j FROM logistica_janelas_efetivas(rid,'2026-10-02');
 PERFORM pg_temp.assert_true(j.coleta_em='2026-10-03 02:00-03'::timestamptz,'regra manual coleta no dia seguinte');
 -- Identificadores especificos, genericos e fallback somente sem identificador.
 INSERT INTO pedidos(numero_pedido,marketplace_module_id,marketplace_integration_id,situacao_pedido_id,metodo_envio_chave,modalidade_logistica,data_venda)
 VALUES('P1','mercadolivre',iid2,2,'novo_id','STANDARD','2026-10-02 09:00') RETURNING id INTO pedido;
 INSERT INTO pedido_snapshots(pedido_id,platform_fields) VALUES(pedido,'{"mercadolivre":{"sla":[{"service":"express"}],"shipment":{"tags":["fast"]}}}');
 PERFORM logistica_associar('mercadolivre','novo_id',mid);
 PERFORM pg_temp.assert_true((SELECT modalidade_logistica_id=mid FROM pedidos WHERE id=pedido),'associacao vale para outra conta');
 PERFORM logistica_associar('mercadolivre','novo_id',especifica,'{"service":"express","tags":["fast"]}');
 PERFORM pg_temp.assert_true((SELECT modalidade_logistica_id=especifica FROM pedidos WHERE id=pedido),'condicoes especificas precedem geral');
 INSERT INTO regras_classificacao_modalidade(module_id,modalidade_id,campo_origem,alvo,valor) VALUES('mercadolivre',mid,'canonical','CANONICA','STANDARD');
 INSERT INTO pedidos(numero_pedido,marketplace_module_id,marketplace_integration_id,situacao_pedido_id,metodo_envio_chave,modalidade_logistica)
 VALUES('ID desconhecido','mercadolivre',iid,2,'sem_associacao','STANDARD') RETURNING id INTO desconhecido;
 PERFORM classificar_pedido_modalidade(desconhecido);
 PERFORM pg_temp.assert_true((SELECT modalidade_logistica_id IS NULL FROM pedidos WHERE id=desconhecido),'identificador desconhecido nao usa fallback');
 INSERT INTO pedidos(numero_pedido,marketplace_module_id,marketplace_integration_id,situacao_pedido_id,modalidade_logistica)
 VALUES('Sem ID','mercadolivre',iid,2,'STANDARD') RETURNING id INTO semchave;
 PERFORM classificar_pedido_modalidade(semchave);
 PERFORM pg_temp.assert_true((SELECT modalidade_logistica_id=mid FROM pedidos WHERE id=semchave),'sem identificador aceita fallback canonico');
 BEGIN
   PERFORM logistica_salvar_modalidade(mid,'{"tipo_prazo":"RELATIVO","offset_etiqueta_min":40,"offset_coleta_min":60}');
   RAISE EXCEPTION 'Mudanca de prazo deveria ser bloqueada';
 EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
 -- Alertas incluem pedidos publicados, vencidos, padrao 60min e encerram na saida.
 UPDATE pedidos SET data_limite_envio='2026-10-02 13:00-03',despachado_em='2026-10-02 10:00-03' WHERE id=pedido;
 PERFORM pg_temp.assert_true(jsonb_array_length(logistica_alertas('2026-10-02 11:59-03'))=0,'alerta ainda fora da antecedencia');
 PERFORM pg_temp.assert_true(jsonb_array_length(logistica_alertas('2026-10-02 12:00-03'))=1,'alerta inicia 60 minutos antes mesmo publicado');
 PERFORM pg_temp.assert_true(jsonb_array_length(logistica_alertas('2026-10-03 12:00-03'))=1,'alerta vencido permanece');
 UPDATE pedidos SET data_limite_envio=NULL WHERE id=pedido;
 PERFORM pg_temp.assert_true((SELECT data_limite_envio='2026-10-02 13:00-03'::timestamptz FROM pedidos WHERE id=pedido),'consulta vazia nao apaga prazo');
 UPDATE pedidos SET marketplace_lifecycle_stage='paid_preparation',marketplace_shipping_status='ready_to_ship',marketplace_shipping_substatus='ready_to_print' WHERE id=pedido;
 PERFORM pg_temp.assert_true((SELECT coleta_confirmada_observada_em IS NULL FROM pedidos WHERE id=pedido),'ready_to_print nao confirma coleta');
 UPDATE pedidos SET marketplace_lifecycle_stage='shipped',marketplace_shipping_substatus='picked_up' WHERE id=pedido;
 SELECT coleta_confirmada_observada_em INTO horario FROM pedidos WHERE id=pedido;
 PERFORM pg_temp.assert_true(horario IS NOT NULL AND (SELECT data_envio_marketplace IS NULL FROM pedidos WHERE id=pedido),'confirma observacao sem inventar horario fisico');
 PERFORM pg_temp.assert_true(jsonb_array_length(logistica_alertas('2026-10-03 12:00-03'))=0,'saida encerra alerta');
 UPDATE pedidos SET marketplace_lifecycle_stage='shipped' WHERE id=pedido;
 PERFORM pg_temp.assert_true((SELECT coleta_confirmada_observada_em=horario FROM pedidos WHERE id=pedido),'confirmacao repetida idempotente');
 UPDATE pedido_snapshots SET logistics='{"deadline":"2026-10-02T13:00:00-03:00","dispatch_deadline_source":"mercadolivre.sla.expected_date"}' WHERE pedido_id=pedido;
 UPDATE pedido_snapshots SET logistics='{}' WHERE pedido_id=pedido;
 PERFORM pg_temp.assert_true((SELECT logistics->>'deadline'='2026-10-02T13:00:00-03:00' FROM pedido_snapshots WHERE pedido_id=pedido),'snapshot vazio preserva prazo e origem');
 -- Rascunhos acompanham a agenda; demandas publicadas conservam seus fatos.
 UPDATE pedidos SET modalidade_logistica_id=mid,data_limite_envio=now()+interval '2 hours',data_pagamento_marketplace=now(),data_venda=now() AT TIME ZONE 'America/Sao_Paulo' WHERE id=semchave;
 INSERT INTO demandas_producao(demanda_id,status) VALUES('TESTE-PUBLICACAO','RASCUNHO') RETURNING id INTO demanda;
 INSERT INTO demandas_pedidos(demanda_id,pedido_id) VALUES(demanda,semchave);
 PERFORM logistica_atualizar_dependentes(iid);
 SELECT data_coleta INTO horario FROM demandas_producao WHERE id=demanda;
 PERFORM pg_temp.assert_true(horario IS NOT NULL,'rascunho recalculado');
 PERFORM pg_temp.assert_true((SELECT jsonb_array_length(escopo_despacho->'janelas')=1 FROM demandas_producao WHERE id=demanda),'rascunho atualiza as faixas registradas');
 UPDATE demandas_producao SET status='PENDENTE',publicado_em=now() WHERE id=demanda;
 PERFORM logistica_atualizar_dependentes(iid);
 PERFORM pg_temp.assert_true((SELECT logistica_divergencia IS NULL FROM demandas_producao WHERE id=demanda),'agenda inalterada nao gera divergencia');
 UPDATE pedidos SET data_limite_envio=now()+interval '3 hours' WHERE id=semchave;
 PERFORM logistica_atualizar_dependentes(iid);
 PERFORM pg_temp.assert_true((SELECT data_coleta=horario AND logistica_divergencia IS NOT NULL FROM demandas_producao WHERE id=demanda),'demanda publicada preserva coleta e informa mudanca de SLA');
 UPDATE pedidos SET data_coleta=now()+interval '5 days',compromisso_logistico_em=now()+interval '5 days' WHERE id=semchave;
 PERFORM pg_temp.assert_true((SELECT data_coleta=horario FROM pedidos WHERE id=semchave),'importacao nao altera coleta de pedido publicado');
 PERFORM logistica_salvar_regra(rid,'{"horario_coleta":"03:00"}','teste');
 PERFORM pg_temp.assert_true((SELECT data_coleta=horario AND logistica_divergencia IS NOT NULL FROM demandas_producao WHERE id=demanda),'mudanca de agenda preserva demanda publicada');
 -- Antecedencia de alerta configurada na regra e etapa pronta aguardando coleta.
 UPDATE pedidos SET data_limite_envio='2026-10-02 13:00-03',situacao_pedido_id=4,modalidade_logistica_id=mid WHERE id=desconhecido;
 PERFORM logistica_salvar_regra(rid,'{"antecedencia_alerta_min":30}','teste');
 PERFORM pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM jsonb_array_elements(logistica_alertas('2026-10-02 12:29-03')) a WHERE (a->>'pedido_id')::int=desconhecido),'respeita antecedencia configurada');
 PERFORM pg_temp.assert_true(EXISTS(SELECT 1 FROM jsonb_array_elements(logistica_alertas('2026-10-02 12:30-03')) a WHERE (a->>'pedido_id')::int=desconhecido AND a->>'etapa'='Pronto, aguardando coleta'),'distingue pronto da preparacao');
 -- Calendario SQL tambem atende importacao e prazo individual relativo.
 v:=logistica_contexto_coleta(iid,'TESTE','2026-10-02 22:00-03','2026-10-02 21:00-03',mid);
 PERFORM pg_temp.assert_true((v->>'data_coleta')::timestamptz='2026-10-03 03:00-03'::timestamptz,'importacao usa a mesma janela SQL');
 v:=logistica_salvar_modalidade(NULL,'{"module_id":"mercadolivre","codigo":"RELATIVA","nome":"Individual","tipo_prazo":"RELATIVO","offset_etiqueta_min":40,"offset_coleta_min":60}');
 mid:=(v->>'id')::int;
 v:=logistica_salvar_regra(NULL,jsonb_build_object('marketplace_integration_id',iid,'modalidade_id',mid,'tipo_envio','COLETA_LOCAL','offset_etiqueta_min',40,'offset_coleta_min',60));
 v:=logistica_contexto_coleta(iid,'RELATIVA','2026-10-02 23:50-03','2026-10-02 23:50-03',mid);
 PERFORM pg_temp.assert_true((v->>'data_coleta')::timestamptz='2026-10-03 00:50-03'::timestamptz,'prazo individual preserva venda e virada de dia');
 INSERT INTO pedidos(numero_pedido,marketplace_module_id,marketplace_integration_id,situacao_pedido_id,
   modalidade_logistica_id,data_pagamento_marketplace,data_limite_envio)
   VALUES('Relativo teste','mercadolivre',iid,2,mid,'2026-10-02 23:50-03','2026-10-03 01:00-03') RETURNING id INTO desconhecido;
 INSERT INTO demandas_producao(demanda_id,status,modalidade_id) VALUES('Relativo teste','RASCUNHO',mid) RETURNING id INTO demanda;
 INSERT INTO demandas_pedidos VALUES(demanda,desconhecido);
 PERFORM logistica_atualizar_dependentes(iid);
 PERFORM pg_temp.assert_true((SELECT data_coleta='2026-10-03 00:50-03'::timestamptz FROM demandas_producao WHERE id=demanda),'rascunho relativo conserva seu prazo individual');
 UPDATE demandas_producao SET status='AGUARDANDO' WHERE id=demanda;
 PERFORM logistica_atualizar_dependentes(iid);
 PERFORM pg_temp.assert_true((SELECT logistica_divergencia IS NULL FROM demandas_producao WHERE id=demanda),'relativo publicado nao produz divergencia falsa de agenda');
 PERFORM logistica_salvar_regra((SELECT id FROM regras_logisticas_integracao WHERE modalidade_id=mid AND marketplace_integration_id=iid LIMIT 1),'{"offset_coleta_min":90}');
 PERFORM pg_temp.assert_true((SELECT data_coleta='2026-10-03 00:50-03'::timestamptz AND logistica_divergencia IS NOT NULL FROM demandas_producao WHERE id=demanda),'alteracao relativa informa divergencia sem mudar publicado');
 INSERT INTO demandas_producao(demanda_id,status,modalidade_id) VALUES('Publicacao direta','AGUARDANDO',mid) RETURNING id INTO demanda;
 INSERT INTO demandas_pedidos VALUES(demanda,desconhecido),(demanda,semchave);
 PERFORM pg_temp.assert_true((SELECT (escopo_despacho->>'prazo_oficial_em')::timestamptz=(SELECT min(data_limite_envio) FROM pedidos WHERE id IN(desconhecido,semchave)) FROM demandas_producao WHERE id=demanda),'publicacao direta congela prazo depois de todos os vinculos');
 -- Catch-up e idempotencia de ocorrencias, sem depender do horario do beat.
 UPDATE logistica_sync_cursores SET ultima_consulta_em='2026-09-29 00:00-03' WHERE nome='janelas-despacho';
 PERFORM pg_temp.assert_true(EXISTS(SELECT 1 FROM janelas_despacho_vencidas('2026-10-03 04:00-03','26 hours')
   WHERE janela_em<'2026-10-03 04:00-03'::timestamptz-interval '26 hours'),'checkpoint recupera interrupcao maior que um dia');
 SELECT count(*) INTO n FROM janelas_despacho_vencidas('2026-10-03 04:00-03','26 hours');
 PERFORM pg_temp.assert_true(n>0,'interrupcao recupera janelas vencidas');
 INSERT INTO janelas_despacho_execucoes(integration_id,modalidade_id,tipo,janela_em)
 SELECT * FROM janelas_despacho_vencidas('2026-10-03 04:00-03','26 hours');
 PERFORM pg_temp.assert_true((SELECT count(*)=0 FROM janelas_despacho_vencidas('2026-10-03 04:00-03','26 hours')),'ocorrencias registradas nao se repetem');
 -- Reserva limita o lote e permite cursor; pedidos publicados participam.
 UPDATE pedidos SET situacao_pedido_id=2 WHERE id=pedido;
 v:=logistica_reservar_sync('teste-envios',100);
 PERFORM pg_temp.assert_true(jsonb_array_length(v)<=40 AND v @> jsonb_build_array(semchave) AND NOT v @> jsonb_build_array(pedido),'reconciliacao inclui publicado e exclui saida confirmada');
 PERFORM pg_temp.assert_true(logistica_reservar_sync('teste-envios',40) IS NULL,'reserva simultanea bloqueada');
 PERFORM pg_temp.assert_true((SELECT count(*)>0 FROM logistica_auditoria WHERE ator='teste'),'alteracoes auditadas');
 PERFORM pg_temp.assert_true(NOT has_function_privilege('authenticated','logistica_salvar_regra(bigint,jsonb,text)','EXECUTE'),'escrita reservada ao backend');
END $test$;
ROLLBACK;
