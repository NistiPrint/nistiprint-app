-- =============================================================
-- MIGRATION: origem ativa de ingest e status canonico marketplace
-- Escopo: Bling, Shopee, Mercado Livre e placeholders/dummies.
-- =============================================================

ALTER TABLE public.installed_integrations
  ADD COLUMN IF NOT EXISTS is_placeholder boolean DEFAULT false;

COMMENT ON COLUMN public.installed_integrations.is_placeholder IS
  'Indica se esta integracao e um placeholder/dummy criado automaticamente para vinculos sem integracao direta.';

CREATE INDEX IF NOT EXISTS idx_installed_integrations_is_placeholder
  ON public.installed_integrations (is_placeholder)
  WHERE is_placeholder = true;

ALTER TABLE public.channel_connections
  ADD COLUMN IF NOT EXISTS ingest_origin_mode text NOT NULL DEFAULT 'erp_bling';

ALTER TABLE public.erp_marketplace_links
  ADD COLUMN IF NOT EXISTS ingest_origin_mode text NOT NULL DEFAULT 'erp_bling';

ALTER TABLE public.channel_connections
  DROP CONSTRAINT IF EXISTS channel_connections_ingest_origin_mode_check;

ALTER TABLE public.channel_connections
  ADD CONSTRAINT channel_connections_ingest_origin_mode_check
  CHECK (ingest_origin_mode IN ('erp_bling', 'marketplace_direct', 'erp_only_dummy'));

ALTER TABLE public.erp_marketplace_links
  DROP CONSTRAINT IF EXISTS erp_marketplace_links_ingest_origin_mode_check;

ALTER TABLE public.erp_marketplace_links
  ADD CONSTRAINT erp_marketplace_links_ingest_origin_mode_check
  CHECK (ingest_origin_mode IN ('erp_bling', 'marketplace_direct', 'erp_only_dummy'));

COMMENT ON COLUMN public.channel_connections.ingest_origin_mode IS
  'Origem autoritativa do ingest: erp_bling, marketplace_direct ou erp_only_dummy';

COMMENT ON COLUMN public.erp_marketplace_links.ingest_origin_mode IS
  'Preferencia sincronizada com channel_connections para origem autoritativa do ingest';

CREATE INDEX IF NOT EXISTS idx_channel_connections_ingest_origin_mode
  ON public.channel_connections (ingest_origin_mode)
  WHERE is_active = true;

ALTER TABLE public.integration_status_mappings
  ADD COLUMN IF NOT EXISTS status_domain text NOT NULL DEFAULT 'order';

COMMENT ON COLUMN public.integration_status_mappings.status_domain IS
  'Dominio do status externo: order, payment, shipping ou package';

DO $$
DECLARE
  constraint_name text;
BEGIN
  SELECT c.conname
    INTO constraint_name
  FROM pg_constraint c
  WHERE c.conrelid = 'public.integration_status_mappings'::regclass
    AND c.contype = 'u'
    AND pg_get_constraintdef(c.oid) LIKE '%module_id%'
    AND pg_get_constraintdef(c.oid) LIKE '%integration_id%'
    AND pg_get_constraintdef(c.oid) LIKE '%external_status_id%'
  LIMIT 1;

  IF constraint_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.integration_status_mappings DROP CONSTRAINT %I', constraint_name);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_integration_status_mappings_domain
  ON public.integration_status_mappings (
    module_id,
    COALESCE(integration_id, 0),
    status_domain,
    external_status_id
  );

CREATE INDEX IF NOT EXISTS idx_integration_status_mappings_domain_status
  ON public.integration_status_mappings(module_id, status_domain, external_status_id)
  WHERE is_active = true;

UPDATE public.integration_status_mappings
SET status_domain = 'order'
WHERE status_domain IS NULL;

DELETE FROM public.integration_status_mappings
WHERE module_id IN ('shopee', 'mercadolivre')
  AND integration_id IS NULL;

INSERT INTO public.integration_status_mappings (
  module_id,
  integration_id,
  status_domain,
  external_status_id,
  external_status_name,
  internal_situacao_pedido_id,
  triggers_demand_consolidation,
  config
) VALUES
  ('shopee', NULL, 'order', 'UNPAID', 'UNPAID', 1, false, '{"action":"sync"}'::jsonb),
  ('shopee', NULL, 'order', 'INVOICE_PENDING', 'INVOICE_PENDING', 2, false, '{"action":"sync"}'::jsonb),
  ('shopee', NULL, 'order', 'READY_TO_SHIP', 'READY_TO_SHIP', 2, true, '{"action":"sync_and_consolidate"}'::jsonb),
  ('shopee', NULL, 'order', 'RETRY_SHIP', 'RETRY_SHIP', 2, true, '{"action":"sync_and_consolidate"}'::jsonb),
  ('shopee', NULL, 'order', 'PROCESSED', 'PROCESSED', 4, true, '{"action":"sync_and_consolidate"}'::jsonb),
  ('shopee', NULL, 'order', 'SHIPPED', 'SHIPPED', 5, false, '{"action":"update_legacy"}'::jsonb),
  ('shopee', NULL, 'order', 'TO_CONFIRM_RECEIVE', 'TO_CONFIRM_RECEIVE', 5, false, '{"action":"update_legacy"}'::jsonb),
  ('shopee', NULL, 'order', 'COMPLETED', 'COMPLETED', 6, false, '{"action":"finish"}'::jsonb),
  ('shopee', NULL, 'order', 'CANCELLED', 'CANCELLED', 7, false, '{"action":"cancel"}'::jsonb),
  ('mercadolivre', NULL, 'payment', 'pending', 'pending', 1, false, '{"action":"sync"}'::jsonb),
  ('mercadolivre', NULL, 'payment', 'in_process', 'in_process', 1, false, '{"action":"sync"}'::jsonb),
  ('mercadolivre', NULL, 'payment', 'authorized', 'authorized', 2, true, '{"action":"sync_and_consolidate"}'::jsonb),
  ('mercadolivre', NULL, 'payment', 'approved', 'approved', 2, true, '{"action":"sync_and_consolidate"}'::jsonb),
  ('mercadolivre', NULL, 'payment', 'rejected', 'rejected', 7, false, '{"action":"cancel"}'::jsonb),
  ('mercadolivre', NULL, 'payment', 'refunded', 'refunded', 7, false, '{"action":"cancel"}'::jsonb),
  ('mercadolivre', NULL, 'shipping', 'to_be_shipped', 'to_be_shipped', 4, true, '{"action":"sync_and_consolidate"}'::jsonb),
  ('mercadolivre', NULL, 'shipping', 'handling', 'handling', 4, true, '{"action":"sync_and_consolidate"}'::jsonb),
  ('mercadolivre', NULL, 'shipping', 'shipped', 'shipped', 5, false, '{"action":"update_legacy"}'::jsonb),
  ('mercadolivre', NULL, 'shipping', 'not_delivered', 'not_delivered', 5, false, '{"action":"update_legacy"}'::jsonb),
  ('mercadolivre', NULL, 'shipping', 'delivered', 'delivered', 6, false, '{"action":"finish"}'::jsonb),
  ('mercadolivre', NULL, 'shipping', 'cancelled', 'cancelled', 7, false, '{"action":"cancel"}'::jsonb);

-- Cria installed_integrations placeholder para conexoes de marketplace ainda
-- dependentes do ERP, mantendo source:<marketplace_integration_id> nos filtros.
WITH candidates AS (
  SELECT DISTINCT
    cc.bling_integration_id,
    cc.marketplace_module_id,
    cc.aggregator_store_id,
    COALESCE(cc.aggregator_store_name, cc.marketplace_module_id || ' (' || cc.aggregator_store_id || ')') AS store_name
  FROM public.channel_connections cc
  JOIN public.integration_modules im ON im.id = cc.marketplace_module_id
  WHERE cc.is_active = true
    AND cc.marketplace_integration_id IS NULL
    AND cc.marketplace_module_id IS NOT NULL
    AND im.tipo = 'marketplace'
), inserted AS (
  INSERT INTO public.installed_integrations (
    module_id,
    instance_name,
    config,
    credentials,
    is_active,
    sync_status,
    is_placeholder,
    created_at,
    updated_at
  )
  SELECT
    marketplace_module_id,
    'Dummy ' || marketplace_module_id || ' via Bling ' || bling_integration_id || ' loja ' || aggregator_store_id,
    jsonb_build_object(
      'dummy', true,
      'ingest_capability', 'erp_only',
      'bling_integration_id', bling_integration_id,
      'bling_loja_id', aggregator_store_id,
      'shop_id', aggregator_store_id,
      'source_note', 'Criado para filtro de origem enquanto o ingest direto nao existe'
    ),
    '{}'::jsonb,
    true,
    'dummy',
    true,
    now(),
    now()
  FROM candidates
  ON CONFLICT (module_id, instance_name) DO UPDATE
    SET config = EXCLUDED.config,
        is_active = true,
        is_placeholder = true,
        updated_at = now()
  RETURNING id, module_id, instance_name, config
)
UPDATE public.channel_connections cc
SET marketplace_integration_id = ii.id,
    ingest_origin_mode = 'erp_only_dummy',
    updated_at = now()
FROM public.installed_integrations ii
WHERE cc.is_active = true
  AND cc.marketplace_integration_id IS NULL
  AND cc.marketplace_module_id = ii.module_id
  AND ii.config->>'dummy' = 'true'
  AND ii.config->>'bling_integration_id' = cc.bling_integration_id::text
  AND ii.config->>'bling_loja_id' = cc.aggregator_store_id;

UPDATE public.erp_marketplace_links eml
SET marketplace_integration_id = cc.marketplace_integration_id,
    ingest_origin_mode = cc.ingest_origin_mode,
    updated_at = now()
FROM public.channel_connections cc
WHERE eml.erp_integration_id = cc.bling_integration_id
  AND eml.erp_store_id = cc.aggregator_store_id
  AND cc.is_active = true;
