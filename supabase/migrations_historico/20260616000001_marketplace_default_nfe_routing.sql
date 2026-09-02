-- Adds explicit NF routing mode to ERP/marketplace links.
-- The default NF emitter for direct marketplace ingest is stored in
-- installed_integrations.config on the marketplace instance:
-- {
--   "default_nfe_erp_integration_id": 2,
--   "default_nfe_shop_id": "204047801",
--   "default_nfe_link_id": "..."
-- }

ALTER TABLE public.erp_marketplace_links
  ADD COLUMN IF NOT EXISTS nf_emission_mode text NOT NULL DEFAULT 'bling';

ALTER TABLE public.erp_marketplace_links
  DROP CONSTRAINT IF EXISTS erp_marketplace_links_nf_emission_mode_check;

ALTER TABLE public.erp_marketplace_links
  ADD CONSTRAINT erp_marketplace_links_nf_emission_mode_check
  CHECK (nf_emission_mode IN ('bling', 'local', 'disabled'));

COMMENT ON COLUMN public.erp_marketplace_links.nf_emission_mode IS
  'NF route exposed by this link: bling, local or disabled.';

CREATE INDEX IF NOT EXISTS idx_erp_marketplace_links_nfe
  ON public.erp_marketplace_links (marketplace_integration_id, nf_emission_mode)
  WHERE nf_emission_mode <> 'disabled';
