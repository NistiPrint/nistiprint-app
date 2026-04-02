-- ============================================
-- Migration: Consolidação de IDs Externos (Fase 5)
-- ============================================
-- Migrar pedidos.codigo_pedido_externo para vinculos_integracao_pedido
-- Remover demandas_producao.horario_coleta (usar channel_snapshot)
-- Criar função de conveniência fn_external_id()
-- ============================================

-- 1. Criar função de conveniência fn_external_id()
-- Substitui o uso direto de pedidos.codigo_pedido_externo
CREATE OR REPLACE FUNCTION "public"."fn_external_id"(
    p_pedido_id integer,
    p_platform varchar DEFAULT NULL
)
RETURNS varchar AS $$
    SELECT id_na_plataforma
    FROM "public"."vinculos_integracao_pedido"
    WHERE pedido_id = p_pedido_id 
      AND (p_platform IS NULL OR plataforma = p_platform)
    ORDER BY 
        CASE WHEN p_platform IS NOT NULL AND plataforma = p_platform THEN 0 ELSE 1 END,
        created_at DESC
    LIMIT 1;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION "public"."fn_external_id"(integer, varchar) IS 
  'Retorna o ID externo de um pedido na plataforma especificada.
   Substitui o campo deprecated pedidos.codigo_pedido_externo.
   Se p_platform for NULL, retorna o primeiro ID externo disponível.';

-- 2. Migrar dados existentes de pedidos.codigo_pedido_externo para vinculos_integracao_pedido
INSERT INTO "public"."vinculos_integracao_pedido" (
    pedido_id,
    plataforma,
    id_na_plataforma,
    dados_brutos,
    created_at
)
SELECT 
    p.id AS pedido_id,
    p.origem AS plataforma,  -- Usar origem como plataforma (SHOPEE, BLING, etc.)
    p.codigo_pedido_externo AS id_na_plataforma,
    jsonb_build_object(
        'migrated_from', 'pedidos.codigo_pedido_externo',
        'migration_date', NOW()
    ) AS dados_brutos,
    p.created_at
FROM "public"."pedidos" p
WHERE p.codigo_pedido_externo IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 
    FROM "public"."vinculos_integracao_pedido" v
    WHERE v.pedido_id = p.id 
      AND v.id_na_plataforma = p.codigo_pedido_externo
  )
ON CONFLICT DO NOTHING;

-- 3. Deprecar campo pedidos.codigo_pedido_externo
COMMENT ON COLUMN "public"."pedidos"."codigo_pedido_externo" IS 
  'DEPRECATED: usar vinculos_integracao_pedido ou função fn_external_id().
   Será removido na Fase 6 após validação.';

-- 4. Remover demandas_producao.horario_coleta (fonte de verdade = channel_snapshot)
-- Primeiro, migrar dados existentes para channel_snapshot (se ainda não tiver)
UPDATE "public"."demandas_producao" d
SET channel_snapshot = jsonb_set(
    COALESCE(d.channel_snapshot, '{}'::jsonb),
    '{horario_coleta}',
    to_jsonb(d.horario_coleta::text)
)
WHERE d.horario_coleta IS NOT NULL
  AND (d.channel_snapshot IS NULL OR d.channel_snapshot = '{}'::jsonb OR d.channel_snapshot->>'horario_coleta' IS NULL);

-- Agora remover a coluna (comentar para rollback - remover na Fase 6)
-- ALTER TABLE "public"."demandas_producao" DROP COLUMN IF EXISTS horario_coleta;

COMMENT ON COLUMN "public"."demandas_producao"."horario_coleta" IS 
  'DEPRECATED: usar channel_snapshot->>''horario_coleta''.
   Será removido na Fase 6 após validação.';

-- 5. Criar índice para função fn_external_id()
CREATE INDEX IF NOT EXISTS "idx_vinculos_pedido_id_platform" 
ON "public"."vinculos_integracao_pedido"(pedido_id, plataforma)
WHERE id_na_plataforma IS NOT NULL;

-- 6. Atualizar OrderService para usar fn_external_id() ou vinculos_integracao_pedido
-- Arquivo: packages/shared/nistiprint_shared/services/order_service.py
-- Substituir: order.codigo_pedido_externo
-- Por: buscar em vinculos_integracao_pedido

-- 7. Atualizar DemandaProducaoService para usar channel_snapshot
-- Arquivo: packages/shared/nistiprint_shared/services/demanda_producao_service.py
-- Substituir: demanda.horario_coleta
-- Por: demanda.channel_snapshot->>'horario_coleta'

-- 8. Criar view de compatibilidade para código legado (opcional)
CREATE OR REPLACE VIEW "public"."pedidos_com_external_id" AS
SELECT 
    p.*,
    COALESCE(
        p.codigo_pedido_externo,
        fn_external_id(p.id, p.origem)
    ) AS external_id
FROM "public"."pedidos" p;

COMMENT ON VIEW "public"."pedidos_com_external_id" IS 
  'View de compatibilidade que retorna pedidos com external_id resolvido.
   Prioriza codigo_pedido_externo (legado), fallback para fn_external_id().
   Será removida na Fase 6.';

-- Grant para a view
GRANT ALL ON TABLE "public"."pedidos_com_external_id" TO "anon";
GRANT ALL ON TABLE "public"."pedidos_com_external_id" TO "authenticated";
GRANT ALL ON TABLE "public"."pedidos_com_external_id" TO "service_role";

-- 9. Atualizar tipos TypeScript (apenas comentário - execução manual no frontend)
-- Arquivo: apps/frontend/src/types/producao.ts
-- Interface Pedido:
--   - codigo_pedido_externo?: string (deprecated)
--   - Adicionar: external_id?: string (resolvido via vinculos)
--   - Adicionar: channel_snapshot?: Record<string, any>
