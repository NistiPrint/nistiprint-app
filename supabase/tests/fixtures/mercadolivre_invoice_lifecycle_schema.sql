-- Simula coluna adicionada em pedidos depois da view original, causa do
-- deslocamento de modalidade_codigo para ingest_origin_mode em producao.
ALTER TABLE pedidos ADD COLUMN ingest_origin_mode text;

CREATE TABLE integration_status_mappings (
  module_id text NOT NULL,
  integration_id integer,
  status_domain text NOT NULL,
  external_status_id text NOT NULL,
  external_status_name text NOT NULL,
  internal_situacao_pedido_id integer,
  lifecycle_stage text NOT NULL,
  stage_rank integer NOT NULL,
  projects_situacao boolean NOT NULL,
  is_terminal boolean NOT NULL DEFAULT false,
  is_modifier boolean NOT NULL DEFAULT false,
  is_active boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX integration_status_mappings_global_key
  ON integration_status_mappings(module_id, status_domain, external_status_id)
  WHERE integration_id IS NULL;
