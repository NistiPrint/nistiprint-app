-- Correcoes de roteamento de demandas, parametrizacao e BOM
-- Data: 2026-04-13

-- ============================================================
-- 1. Backfill channel_connections dual-FK
-- ============================================================

ALTER TABLE public.channel_connections
  DROP CONSTRAINT IF EXISTS channel_connections_channel_id_integration_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_connections_direct_integration_active
  ON public.channel_connections (channel_id, integration_id)
  WHERE aggregator_store_id IS NULL
    AND integration_id IS NOT NULL
    AND is_active = true;

UPDATE public.channel_connections cc
SET bling_integration_id = cc.integration_id
FROM public.installed_integrations ii
WHERE cc.integration_id = ii.id
  AND ii.module_id = 'bling'
  AND cc.bling_integration_id IS NULL;

UPDATE public.channel_connections cc
SET
  bling_integration_id = COALESCE(cc.bling_integration_id, icc.bling_integration_id),
  marketplace_integration_id = COALESCE(cc.marketplace_integration_id, icc.marketplace_integration_id)
FROM public.integracao_canais_config icc
WHERE icc.is_active = true
  AND icc.canal_venda_id = cc.channel_id
  AND icc.bling_loja_id::text = cc.aggregator_store_id
  AND (
    cc.bling_integration_id IS NULL
    OR cc.marketplace_integration_id IS NULL
  );

UPDATE public.channel_connections cc
SET marketplace_integration_id = eml.marketplace_integration_id
FROM public.erp_marketplace_links eml
WHERE eml.erp_integration_id = COALESCE(cc.bling_integration_id, cc.integration_id)
  AND eml.erp_store_id = cc.aggregator_store_id
  AND eml.marketplace_integration_id IS NOT NULL
  AND cc.marketplace_integration_id IS NULL;

-- ============================================================
-- 2. View canonica para debug/roteamento
-- ============================================================

CREATE OR REPLACE VIEW public.v_channel_routing_context AS
SELECT
  cc.id AS connection_id,
  cc.channel_id,
  cv.nome AS channel_name,
  cv.slug AS channel_slug,
  cc.integration_id,
  COALESCE(cc.bling_integration_id, eml.erp_integration_id) AS erp_integration_id,
  erp.module_id AS erp_module_id,
  erp.instance_name AS erp_instance_name,
  cc.aggregator_store_id AS erp_store_id,
  cc.aggregator_store_name AS erp_store_name,
  COALESCE(cc.marketplace_integration_id, eml.marketplace_integration_id) AS marketplace_integration_id,
  marketplace.module_id AS marketplace_module_id,
  marketplace.instance_name AS marketplace_instance_name,
  COALESCE(cc.config, '{}'::jsonb) || COALESCE(eml.config, '{}'::jsonb) AS config,
  cc.is_active,
  cc.sync_status,
  cc.last_sync,
  cc.created_at,
  cc.updated_at
FROM public.channel_connections cc
LEFT JOIN public.canais_venda cv
  ON cv.id = cc.channel_id
LEFT JOIN public.erp_marketplace_links eml
  ON eml.erp_integration_id = COALESCE(cc.bling_integration_id, cc.integration_id)
 AND eml.erp_store_id = cc.aggregator_store_id
LEFT JOIN public.installed_integrations erp
  ON erp.id = COALESCE(cc.bling_integration_id, eml.erp_integration_id)
LEFT JOIN public.installed_integrations marketplace
  ON marketplace.id = COALESCE(cc.marketplace_integration_id, eml.marketplace_integration_id);

COMMENT ON VIEW public.v_channel_routing_context IS
'Contexto canonico para resolver loja ERP -> canal operacional -> marketplace instalado.';

-- ============================================================
-- 3. Parametrizacao de status externo
-- ============================================================

CREATE TABLE IF NOT EXISTS public.integration_status_mappings (
  id bigserial PRIMARY KEY,
  module_id text NOT NULL,
  integration_id integer NULL REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
  external_status_id text NOT NULL,
  external_status_name text NULL,
  internal_situacao_pedido_id integer NULL REFERENCES public.situacoes_pedido(id),
  triggers_demand_consolidation boolean NOT NULL DEFAULT false,
  is_active boolean NOT NULL DEFAULT true,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (module_id, integration_id, external_status_id)
);

CREATE INDEX IF NOT EXISTS idx_integration_status_mappings_module_status
  ON public.integration_status_mappings(module_id, external_status_id)
  WHERE is_active = true;

DELETE FROM public.integration_status_mappings
WHERE module_id = 'bling'
  AND integration_id IS NULL
  AND external_status_id IN ('6', '15', '9', '12', '24');

INSERT INTO public.integration_status_mappings (
  module_id,
  integration_id,
  external_status_id,
  external_status_name,
  internal_situacao_pedido_id,
  triggers_demand_consolidation,
  config
) VALUES
  ('bling', NULL, '6',  'Em Aberto',    1, false, '{"action":"sync"}'::jsonb),
  ('bling', NULL, '15', 'Em Andamento', 2, true,  '{"action":"sync_and_consolidate"}'::jsonb),
  ('bling', NULL, '9',  'Atendido',     5, false, '{"action":"update_legacy"}'::jsonb),
  ('bling', NULL, '12', 'Cancelado',    7, false, '{"action":"cancel"}'::jsonb),
  ('bling', NULL, '24', 'Verificado',   4, false, '{"action":"update_legacy"}'::jsonb);

-- ============================================================
-- 4. Auditoria e bloqueio: produto acabado nao pode ser componente
-- ============================================================

CREATE OR REPLACE VIEW public.v_auditoria_bom_componentes_invalidos AS
SELECT
  ft.id AS ficha_tecnica_id,
  ft.produto_pai_id,
  pai.sku AS produto_pai_sku,
  pai.nome AS produto_pai_nome,
  pai.tipo_produto AS produto_pai_tipo,
  ft.componente_id,
  componente.sku AS componente_sku,
  componente.nome AS componente_nome,
  componente.tipo_produto AS componente_tipo,
  ft.quantidade_necessaria,
  CASE
    WHEN componente.tipo_produto = 'PRODUTO_ACABADO' THEN 'COMPONENTE_PRODUTO_ACABADO'
    ELSE 'OK'
  END AS status_auditoria
FROM public.ficha_tecnica ft
LEFT JOIN public.produtos pai
  ON pai.id = ft.produto_pai_id
LEFT JOIN public.produtos componente
  ON componente.id = ft.componente_id
WHERE componente.tipo_produto = 'PRODUTO_ACABADO';

CREATE OR REPLACE FUNCTION public.validar_componente_ficha_tecnica()
RETURNS trigger AS $$
DECLARE
  v_tipo_produto text;
BEGIN
  SELECT tipo_produto::text
    INTO v_tipo_produto
  FROM public.produtos
  WHERE id = NEW.componente_id;

  IF v_tipo_produto = 'PRODUTO_ACABADO' THEN
    RAISE EXCEPTION 'Produto acabado nao pode ser componente de BOM (componente_id=%)', NEW.componente_id
      USING ERRCODE = '23514';
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validar_componente_ficha_tecnica ON public.ficha_tecnica;
CREATE TRIGGER trg_validar_componente_ficha_tecnica
BEFORE INSERT OR UPDATE OF componente_id ON public.ficha_tecnica
FOR EACH ROW
EXECUTE FUNCTION public.validar_componente_ficha_tecnica();

-- ============================================================
-- 5. Remover overload antigo que torna a RPC ambigua no PostgREST
-- ============================================================

DROP FUNCTION IF EXISTS public.reconciliar_item_estoque(
  integer,
  integer,
  jsonb,
  jsonb,
  character varying,
  character varying
);
