-- =============================================================
-- MIGRATION: Fix find_marketplace_by_bling_loja RPC
-- Data: 2026-04-27
-- Escopo: Corrigir RPC para usar channel_connections como fonte de verdade
--          em vez de installed_integrations.config->>'bling_loja_id' (modelo 1:1)
-- =============================================================

-- Drop old version (1:1 model via installed_integrations.config)
DROP FUNCTION IF EXISTS public.find_marketplace_by_bling_loja(text);

-- Create new version (N:N model via channel_connections)
CREATE OR REPLACE FUNCTION public.find_marketplace_by_bling_loja(
    p_loja_id text,
    p_bling_integration_id integer DEFAULT NULL
)
RETURNS SETOF installed_integrations
LANGUAGE sql STABLE AS $$
    SELECT ii.*
      FROM channel_connections cc
      JOIN installed_integrations ii ON ii.id = cc.marketplace_integration_id
     WHERE cc.aggregator_store_id = p_loja_id
       AND cc.is_active = true
       AND ii.is_active = true
       AND (p_bling_integration_id IS NULL
            OR cc.bling_integration_id = p_bling_integration_id)
     LIMIT 1;
$$;

-- Grant permissions
GRANT EXECUTE ON FUNCTION public.find_marketplace_by_bling_loja(text, integer) TO authenticated, anon, service_role;

-- Comment
COMMENT ON FUNCTION public.find_marketplace_by_bling_loja IS
'Resolves marketplace integration by Bling loja_id using channel_connections as source of truth (N:N model). Optional p_bling_integration_id parameter for disambiguation when same loja_id appears in multiple Bling instances.';
