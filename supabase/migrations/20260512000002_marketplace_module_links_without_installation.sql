-- =============================================================
-- MIGRATION: Marketplace module links without installed instances
-- Date: 2026-05-12
-- Scope:
--   - Allow ERP links to reference a marketplace module directly.
--   - Allow channel connections to keep the module slug even when there is
--     no installed marketplace integration yet.
-- =============================================================

ALTER TABLE public.erp_marketplace_links
    ADD COLUMN IF NOT EXISTS marketplace_module_id varchar(100);

ALTER TABLE public.channel_connections
    ADD COLUMN IF NOT EXISTS marketplace_module_id varchar(100);

CREATE INDEX IF NOT EXISTS idx_erp_links_marketplace_module
    ON public.erp_marketplace_links(marketplace_module_id);

CREATE INDEX IF NOT EXISTS idx_channel_connections_marketplace_module
    ON public.channel_connections(marketplace_module_id)
    WHERE is_active = true;

UPDATE public.erp_marketplace_links eml
   SET marketplace_module_id = ii.module_id,
       updated_at = now()
  FROM public.installed_integrations ii
 WHERE eml.marketplace_integration_id = ii.id
   AND eml.marketplace_module_id IS NULL;

UPDATE public.channel_connections cc
   SET marketplace_module_id = ii.module_id,
       updated_at = now()
  FROM public.installed_integrations ii
 WHERE cc.marketplace_integration_id = ii.id
   AND cc.marketplace_module_id IS NULL;

COMMENT ON COLUMN public.erp_marketplace_links.marketplace_module_id IS
    'Catalog module slug for the marketplace when no installed integration exists yet.';

COMMENT ON COLUMN public.channel_connections.marketplace_module_id IS
    'Catalog module slug used to resolve channel/order origin without an installed marketplace integration.';
