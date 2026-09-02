-- ============================================
-- Migration: Add Index para Lookup Rápido
-- ============================================
-- Adiciona índice em channel_connections para lookup rápido:
-- aggregator_store_id (loja Bling) → bling_integration_id
-- ============================================

-- 1. Criar índice composto para lookup rápido
CREATE INDEX IF NOT EXISTS "idx_channel_connections_store_to_integration"
ON "public"."channel_connections"("aggregator_store_id", "bling_integration_id")
WHERE "is_active" = true;

COMMENT ON INDEX "public"."idx_channel_connections_store_to_integration" IS
  'Lookup rápido: dado aggregator_store_id (loja Bling), encontra bling_integration_id';

-- 2. Criar índice adicional para marketplace_integration_id
CREATE INDEX IF NOT EXISTS "idx_channel_connections_marketplace"
ON "public"."channel_connections"("marketplace_integration_id")
WHERE "is_active" = true AND "marketplace_integration_id" IS NOT NULL;

COMMENT ON INDEX "public"."idx_channel_connections_marketplace" IS
  'Lookup rápido: encontrar channel_connections por marketplace_integration_id';

-- 3. Índice para bling_integration_id
CREATE INDEX IF NOT EXISTS "idx_channel_connections_bling"
ON "public"."channel_connections"("bling_integration_id")
WHERE "is_active" = true AND "bling_integration_id" IS NOT NULL;

COMMENT ON INDEX "public"."idx_channel_connections_bling" IS
  'Lookup rápido: encontrar channel_connections por bling_integration_id';
