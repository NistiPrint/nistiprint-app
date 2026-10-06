-- Complemento do esquema minimo de logistica para leituras de despacho.
ALTER TABLE pedidos ADD COLUMN codigo_pedido_externo text, ADD COLUMN cliente_nome text,
 ADD COLUMN total_pedido numeric, ADD COLUMN pack_id text,
 ADD COLUMN erp_integration_id integer, ADD COLUMN erp_store_id text,
 ADD COLUMN erp_order_id text, ADD COLUMN erp_order_number text,
 ADD COLUMN prazo_postagem_tentativas integer DEFAULT 0,
 ADD COLUMN prazo_postagem_proxima_tentativa timestamptz, ADD COLUMN prazo_postagem_motivo text;
ALTER TABLE pedido_snapshots ADD COLUMN updated_at timestamptz DEFAULT now();
CREATE TABLE pedidos_shopee(codigo_pedido text PRIMARY KEY, ship_by_date timestamptz, dias_para_envio integer);
CREATE TABLE itens_pedido(id serial PRIMARY KEY, pedido_id integer, quantidade numeric);
CREATE INDEX ON itens_pedido(pedido_id);
CREATE VIEW vw_pedidos_pendentes_despacho WITH (security_invoker=true) AS
 SELECT p.*, m.codigo AS modalidade_codigo, m.nome AS modalidade_nome,
        m.tipo_prazo AS modalidade_tipo_prazo, m.ordem_exibicao AS modalidade_ordem,
        i.instance_name AS marketplace_nome
 FROM pedidos p LEFT JOIN modalidades_logisticas m ON m.id=p.modalidade_logistica_id
 LEFT JOIN installed_integrations i ON i.id=p.marketplace_integration_id
 WHERE p.situacao_pedido_id=2 AND p.despachado_em IS NULL
 AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment,false))
 AND NOT EXISTS (SELECT 1 FROM demandas_pedidos dp JOIN demandas_producao d ON d.id=dp.demanda_id
    WHERE dp.pedido_id=p.id AND d.status NOT IN ('RASCUNHO','CANCELADO','Cancelado'));
CREATE FUNCTION despacho_aba_do_bucket(text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
 SELECT CASE $1 WHEN 'amanha' THEN 'amanha' WHEN 'depois' THEN 'proximos' ELSE 'hoje' END $$;
CREATE FUNCTION despacho_composicao_situacao(date) RETURNS TABLE(integration_id integer,situacao_id integer,situacao_nome text,qtd_pedidos integer)
 LANGUAGE sql STABLE AS $$ SELECT marketplace_integration_id,2,'Em Andamento',count(*)::integer
 FROM vw_pedidos_pendentes_despacho GROUP BY 1 $$;
CREATE FUNCTION despacho_rascunhos_abertos(date) RETURNS TABLE(integration_id integer,modalidade_id integer,qtd_pedidos integer)
 LANGUAGE sql STABLE AS $$ SELECT NULL::integer,NULL::integer,0 WHERE false $$;
CREATE FUNCTION despacho_lotes(integer) RETURNS TABLE(modalidade_id integer,lote_chave text,modalidade_ids integer[],lote_nome text,entrega_rapida boolean)
 LANGUAGE sql STABLE AS $$ SELECT m.id,m.id::text,ARRAY[m.id],m.nome,m.entrega_rapida FROM modalidades_logisticas m
 WHERE m.module_id=(SELECT module_id FROM installed_integrations WHERE id=$1) $$;
CREATE FUNCTION pedidos_pacotes(integer[]) RETURNS TABLE(pedido_id integer,irmaos integer,irmaos_ids integer[])
 LANGUAGE sql STABLE AS $$ SELECT id,0,'{}'::integer[] FROM pedidos WHERE id=ANY($1) $$;
