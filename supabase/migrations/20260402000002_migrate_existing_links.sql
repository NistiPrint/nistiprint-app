-- ============================================
-- Migration: Migrar Vínculos Existentes
-- ============================================
-- Migra vínculos existentes de channel_connections 
-- para a nova tabela erp_marketplace_links
-- ============================================

-- 1. Migrar vínculos de channel_connections para erp_marketplace_links
INSERT INTO "public"."erp_marketplace_links" (
    "erp_integration_id",
    "marketplace_integration_id",
    "erp_store_id",
    "store_name",
    "config"
)
SELECT 
    cc."bling_integration_id" AS "erp_integration_id",
    cc."marketplace_integration_id" AS "marketplace_integration_id",
    cc."aggregator_store_id" AS "erp_store_id",
    cc."aggregator_store_name" AS "store_name",
    COALESCE(cc."config", '{}') AS "config"
FROM "public"."channel_connections" cc
WHERE 
    cc."bling_integration_id" IS NOT NULL
    AND cc."marketplace_integration_id" IS NOT NULL
    AND cc."is_active" = true
ON CONFLICT ("erp_integration_id", "marketplace_integration_id") DO NOTHING;

-- 2. Log de quantos registros foram migrados
DO $$
DECLARE
    migrated_count integer;
BEGIN
    SELECT COUNT(*) INTO migrated_count
    FROM "public"."erp_marketplace_links";
    
    RAISE NOTICE 'Migração concluída: % vínculos migrados para erp_marketplace_links', migrated_count;
END $$;

-- 3. Nota: Após esta migração, os vínculos em channel_connections continuam existindo
-- para manter compatibilidade com o código legado.
-- O novo código deve usar erp_marketplace_links para configurações de ERP.
