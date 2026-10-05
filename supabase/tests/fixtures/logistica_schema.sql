-- Esquema minimo, sem dados de clientes, para PostgreSQL/PGlite isolado.
CREATE ROLE anon;
CREATE ROLE authenticated;
CREATE ROLE service_role BYPASSRLS;
CREATE TABLE installed_integrations(id serial PRIMARY KEY,module_id varchar NOT NULL,instance_name text,is_active boolean DEFAULT true);
CREATE TABLE modalidades_logisticas(id serial PRIMARY KEY,module_id varchar NOT NULL,codigo varchar NOT NULL,nome varchar NOT NULL,
 tipo_prazo varchar NOT NULL CHECK(tipo_prazo IN ('FIXO','RELATIVO')),politica_lote varchar NOT NULL DEFAULT 'LOTE',
 nivel_interrupcao smallint NOT NULL DEFAULT 0,corte_horario time,coleta_horario time,coleta_dia_offset smallint NOT NULL DEFAULT 0,
 offset_etiqueta_min integer,offset_coleta_min integer,cor varchar,ordem_exibicao smallint NOT NULL DEFAULT 100,
 ativo boolean NOT NULL DEFAULT true,entra_na_torre boolean NOT NULL DEFAULT true,entrega_rapida boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),UNIQUE(module_id,codigo));
CREATE TABLE pontos_coleta(id serial PRIMARY KEY,nome text,horario_fechamento time);
CREATE TABLE regras_logisticas_integracao(id bigserial PRIMARY KEY,marketplace_integration_id integer NOT NULL REFERENCES installed_integrations,
 modalidade varchar NOT NULL,tipo_envio varchar NOT NULL,horario_limite time,ponto_coleta_id integer REFERENCES pontos_coleta,
 dias_semana smallint[] DEFAULT ARRAY[1,2,3,4,5,6,7],prioridade_uso integer DEFAULT 1,ativo boolean DEFAULT true,descricao text,
 horario_corte time,horario_coleta time,modalidade_id integer REFERENCES modalidades_logisticas,
 coleta_dia_offset smallint NOT NULL DEFAULT 0,offset_etiqueta_min integer,offset_coleta_min integer,
 created_at timestamptz DEFAULT now(),updated_at timestamptz DEFAULT now());
CREATE TABLE regra_logistica_modalidades(regra_id bigint REFERENCES regras_logisticas_integracao,modalidade_id integer REFERENCES modalidades_logisticas,
 created_at timestamptz DEFAULT now(),PRIMARY KEY(regra_id,modalidade_id));
CREATE TABLE regras_classificacao_modalidade(id serial PRIMARY KEY,module_id varchar NOT NULL,integration_id integer,
 modalidade_id integer NOT NULL REFERENCES modalidades_logisticas,campo_origem varchar NOT NULL,alvo varchar NOT NULL DEFAULT 'CHAVE',
 operador varchar NOT NULL DEFAULT 'IGUAL',valor text NOT NULL,case_sensitive boolean NOT NULL DEFAULT false,prioridade smallint NOT NULL DEFAULT 100,
 ativo boolean NOT NULL DEFAULT true,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE pedidos(id serial PRIMARY KEY,numero_pedido varchar NOT NULL,marketplace_module_id text,marketplace_integration_id integer,
 marketplace_order_id text,situacao_pedido_id integer,marketplace_lifecycle_stage text,marketplace_shipping_status text,marketplace_shipping_substatus text,
 marketplace_status_updated_at timestamptz,data_venda timestamp,data_limite_envio timestamptz,data_coleta timestamptz,data_envio_marketplace timestamptz,
 data_pagamento_marketplace timestamptz,data_compra_marketplace timestamptz,despachado_em timestamptz,is_fulfillment boolean,
 modalidade_logistica_id integer,modalidade_regra_id integer,modalidade_classificada_em timestamptz,modalidade_logistica text,
 metodo_envio_chave text,metodo_envio_rotulo text,compromisso_logistico_em timestamptz);
CREATE TABLE pedido_snapshots(id bigserial PRIMARY KEY,pedido_id integer NOT NULL UNIQUE REFERENCES pedidos,platform_fields jsonb NOT NULL DEFAULT '{}',logistics jsonb NOT NULL DEFAULT '{}');
CREATE TABLE demandas_producao(id serial PRIMARY KEY,demanda_id varchar NOT NULL,status varchar DEFAULT 'PENDENTE',publicado_em timestamptz,
 modalidade_id integer,data_coleta timestamptz,escopo_despacho jsonb);
CREATE TABLE demandas_pedidos(demanda_id integer REFERENCES demandas_producao,pedido_id integer REFERENCES pedidos);
CREATE TABLE janelas_despacho_execucoes(integration_id integer,modalidade_id integer,tipo text,janela_em timestamptz);
CREATE TABLE metodos_envio_observados(module_id text,campo_origem text,valor_bruto text,valor_normalizado text,rotulo_bruto text,
 ocorrencias integer,primeira_ocorrencia_em timestamptz,ultima_ocorrencia_em timestamptz,pedido_exemplo_id integer);
CREATE FUNCTION regras_da_modalidade(p_modalidade_id integer,p_integration_id integer) RETURNS SETOF regras_logisticas_integracao
 LANGUAGE sql STABLE AS $$ SELECT r.* FROM regras_logisticas_integracao r JOIN regra_logistica_modalidades rm ON rm.regra_id=r.id
 WHERE r.ativo AND rm.modalidade_id=p_modalidade_id AND r.marketplace_integration_id=p_integration_id $$;
CREATE FUNCTION tg_regra_logistica_sync_modalidade() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER regra_logistica_sync_modalidade BEFORE INSERT OR UPDATE ON regras_logisticas_integracao FOR EACH ROW EXECUTE FUNCTION tg_regra_logistica_sync_modalidade();
