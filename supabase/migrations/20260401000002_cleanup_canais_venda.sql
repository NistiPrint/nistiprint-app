-- ============================================
-- Migration: Limpeza de sales_channels (Fase 3)
-- ============================================
-- Remove campos redundantes de canais_venda
-- Torna plataforma_id nullable
-- ============================================

-- 1. Tornar plataforma_id nullable (já deve ser, mas garantimos)
ALTER TABLE "public"."canais_venda" 
ALTER COLUMN "plataforma_id" DROP NOT NULL;

-- 2. Remover conta_bling_id (agora em channel_connections.aggregator_store_id)
-- Nota: Não removemos imediatamente para permitir rollback. Apenas deprecamos.
COMMENT ON COLUMN "public"."canais_venda"."conta_bling_id" IS 
  'DEPRECATED: usar channel_connections.aggregator_store_id. Será removido na Fase 6.';

-- 3. Remover bling_loja_id_principal e integration_id_principal (redundantes com channel_connections)
-- Nota: Não removemos imediatamente para permitir rollback. Apenas deprecamos.
COMMENT ON COLUMN "public"."canais_venda"."bling_loja_id_principal" IS 
  'DEPRECATED: usar channel_connections.aggregator_store_id. Será removido na Fase 6.';

COMMENT ON COLUMN "public"."canais_venda"."integration_id_principal" IS 
  'DEPRECATED: usar channel_connections.integration_id. Será removido na Fase 6.';

-- 4. Adicionar comentário em horario_coleta como fonte primária
COMMENT ON COLUMN "public"."canais_venda"."horario_coleta" IS 
  'Fonte primária de horário de coleta.
   Demandas herdam este valor no momento da criação e não são sincronizadas retroativamente.';

-- 5. Adicionar comentário em flex e fulfillment
COMMENT ON COLUMN "public"."canais_venda"."flex" IS 
  'Indica se o canal suporta entrega flexível/urgente (Entrega Rápida Shopee).
   Pedidos herdam este valor via trigger no momento da criação.';

COMMENT ON COLUMN "public"."canais_venda"."fulfillment" IS 
  'Indica se o canal usa serviço de fulfillment externo.
   Demandas herdam este valor no momento da criação.';

-- 6. Criar índice para plataforma_id (agora nullable)
CREATE INDEX IF NOT EXISTS "idx_canais_venda_plataforma_id" 
ON "public"."canais_venda"("plataforma_id") 
WHERE "plataforma_id" IS NOT NULL;

-- 7. Atualizar tipos TypeScript (apenas comentário - execução manual no frontend)
-- Arquivo: apps/frontend/src/types/producao.ts
-- Interface CanalVenda:
--   - plataforma_id?: number (tornar optional)
--   - conta_bling_id?: string (deprecated)
--   - Manter flex, fulfillment, horario_coleta
