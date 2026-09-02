-- Allow one marketplace integration to be served by multiple Bling accounts,
-- each with its own shop.id / ERP store id.

ALTER TABLE public.erp_marketplace_links
  DROP CONSTRAINT IF EXISTS erp_marketplace_links_erp_integration_id_marketplace_integration_id_key;

DROP INDEX IF EXISTS public.erp_marketplace_links_erp_integration_id_marketplace_integration_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_erp_marketplace_links_operational_key
  ON public.erp_marketplace_links (erp_integration_id, marketplace_integration_id, erp_store_id);

COMMENT ON INDEX public.ux_erp_marketplace_links_operational_key IS
  'Operational key for fulfillment routing: marketplace origin + ERP account + shop.id.';
