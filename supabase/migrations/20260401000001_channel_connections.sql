-- ============================================
-- Migration: Channel Connections (Fase 2)
-- ============================================
-- Renomeia integracao_canais_config para channel_connections
-- Padroniza nomenclatura para padrão de mercado
-- ============================================

-- 1. Criar nova tabela channel_connections com nomenclatura padronizada
CREATE TABLE IF NOT EXISTS "public"."channel_connections" (
    "id" uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    
    -- O canal de venda (destino dos pedidos)
    "channel_id" integer NOT NULL REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE,
    
    -- A integração ativa (fonte dos pedidos)
    "integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL,
    
    -- Para integrações via agregador (ex: Bling): qual loja/conta dentro do agregador
    -- Null quando a integração é direta (Shopee OAuth conectado diretamente)
    "aggregator_store_id" varchar(255),
    "aggregator_store_name" varchar(255),
    
    -- Configuração específica desta conexão (mapeamento de status, filtros, etc.)
    "config" jsonb DEFAULT '{}',
    
    -- Status e sincronismo
    "is_active" boolean DEFAULT true,
    "last_sync" timestamp with time zone,
    "sync_status" varchar(50) DEFAULT 'pending',
    
    -- Timestamps
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    
    -- Constraints únicas
    UNIQUE ("channel_id", "integration_id")
);

-- 2. Comentários de documentação
COMMENT ON TABLE "public"."channel_connections" IS 
  'Vínculo explícito entre canal de venda e integração (substitui integracao_canais_config)';

COMMENT ON COLUMN "public"."channel_connections"."channel_id" IS 
  'Referência ao canal de venda (ex: Shopee, Amazon)';

COMMENT ON COLUMN "public"."channel_connections"."integration_id" IS 
  'Referência à instância de integração em installed_integrations';

COMMENT ON COLUMN "public"."channel_connections"."aggregator_store_id" IS 
  'Preenchido apenas quando a integração é um agregador (ex: Bling).
   Identifica qual loja dentro do agregador pertence a este canal.
   Ex: bling_loja_id = 204047801, 205218967';

COMMENT ON COLUMN "public"."channel_connections"."aggregator_store_name" IS 
  'Nome amigável da loja no agregador (ex: "Shopee Antiga", "Shopee Nova")';

COMMENT ON COLUMN "public"."channel_connections"."config" IS 
  'Configurações específicas desta conexão (mapeamento de status, filtros, etc.)';

-- 3. Migrar dados de integracao_canais_config para channel_connections
INSERT INTO "public"."channel_connections" (
    id,
    channel_id,
    integration_id,
    aggregator_store_id,
    aggregator_store_name,
    config,
    is_active,
    last_sync,
    sync_status,
    created_at,
    updated_at
)
SELECT
    icc.id,
    icc.canal_venda_id AS channel_id,
    -- Priorizar bling_integration_id se existir, senão integration_id legado
    COALESCE(icc.bling_integration_id, icc.integration_id) AS integration_id,
    icc.bling_loja_id AS aggregator_store_id,
    -- Nome da loja: usar plataforma_nome + bling_loja_id como fallback
    CONCAT(
        COALESCE(icc.plataforma_nome, 'Loja'),
        ' (',
        icc.bling_loja_id,
        ')'
    ) AS aggregator_store_name,
    COALESCE(icc.config_json, '{}') AS config,
    icc.is_active,
    NULL AS last_sync,
    COALESCE(icc.is_primary, false) AS sync_status, -- Reutilizando campo
    icc.created_at,
    icc.updated_at
FROM "public"."integracao_canais_config" icc
WHERE icc.is_active = true
ON CONFLICT (channel_id, integration_id) DO NOTHING;

-- 4. Criar índices para performance
CREATE INDEX IF NOT EXISTS "idx_channel_connections_channel_id" 
ON "public"."channel_connections"("channel_id") 
WHERE "is_active" = true;

CREATE INDEX IF NOT EXISTS "idx_channel_connections_integration_id" 
ON "public"."channel_connections"("integration_id") 
WHERE "is_active" = true;

CREATE INDEX IF NOT EXISTS "idx_channel_connections_aggregator_store_id" 
ON "public"."channel_connections"("aggregator_store_id") 
WHERE "aggregator_store_id" IS NOT NULL AND "is_active" = true;

-- Índice composto para busca rápida por canal + agregador
CREATE UNIQUE INDEX IF NOT EXISTS "idx_channel_connections_channel_aggregator" 
ON "public"."channel_connections"("channel_id", "aggregator_store_id") 
WHERE "aggregator_store_id" IS NOT NULL AND "is_active" = true;

-- 5. Criar trigger para updated_at
CREATE OR REPLACE TRIGGER "update_channel_connections_updated_at"
BEFORE UPDATE ON "public"."channel_connections"
FOR EACH ROW
EXECUTE FUNCTION "public"."update_updated_at_column"();

-- 6. Criar view de compatibilidade integracao_canais_config
-- Esta view será removida na Fase 6
CREATE OR REPLACE VIEW "public"."integracao_canais_config_compat" AS
SELECT
    cc.id,
    cc.channel_id AS canal_venda_id,
    cc.integration_id,
    cc.aggregator_store_id AS bling_loja_id,
    cc.aggregator_store_name,
    -- Extrair plataforma_nome do aggregator_store_name ou usar fallback
    CASE 
        WHEN cc.aggregator_store_name LIKE '%Shopee%' THEN 'shopee'
        WHEN cc.aggregator_store_name LIKE '%Amazon%' THEN 'amazon'
        WHEN cc.aggregator_store_name LIKE '%Mercado Livre%' THEN 'mercadolivre'
        WHEN cc.aggregator_store_name LIKE '%Shein%' THEN 'shein'
        WHEN cc.aggregator_store_name LIKE '%TikTok%' THEN 'tiktokshop'
        ELSE NULL
    END AS plataforma_nome,
    cc.is_active,
    -- is_primary: true se for o primeiro vínculo ativo do canal
    ROW_NUMBER() OVER (PARTITION BY cc.channel_id ORDER BY cc.created_at) = 1 AS is_primary,
    cc.config AS config_json,
    cc.created_at,
    cc.updated_at
FROM "public"."channel_connections" cc
WHERE cc.is_active = true;

-- Grant para a view
GRANT ALL ON TABLE "public"."integracao_canais_config_compat" TO "anon";
GRANT ALL ON TABLE "public"."integracao_canais_config_compat" TO "authenticated";
GRANT ALL ON TABLE "public"."integracao_canais_config_compat" TO "service_role";

-- 7. Permissões para channel_connections
ALTER TABLE "public"."channel_connections" DISABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE "public"."channel_connections" TO "anon";
GRANT ALL ON TABLE "public"."channel_connections" TO "authenticated";
GRANT ALL ON TABLE "public"."channel_connections" TO "service_role";

-- 8. Atualizar installed_integrations para adicionar marketplace_integration_id e bling_integration_id
-- (já existe da migration 20260328000000, mas garantimos que esteja presente)
ALTER TABLE "public"."integracao_canais_config"
ADD COLUMN IF NOT EXISTS "bling_integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS "marketplace_integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;

-- 9. Adicionar colunas auxiliares em channel_connections para dual-FK (opcional, para transição)
ALTER TABLE "public"."channel_connections"
ADD COLUMN IF NOT EXISTS "bling_integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS "marketplace_integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;

COMMENT ON COLUMN "public"."channel_connections"."bling_integration_id" IS 
  'installed_integrations (module_id=bling) — conta Bling usada para API/token deste vínculo';

COMMENT ON COLUMN "public"."channel_connections"."marketplace_integration_id" IS 
  'installed_integrations (shopee, amazon, etc.) — instância marketplace associada a esta loja Bling';

-- Índices para os novos FKs
CREATE INDEX IF NOT EXISTS "idx_channel_connections_bling_integration_id" 
ON "public"."channel_connections" ("bling_integration_id") 
WHERE "is_active" = true;

CREATE INDEX IF NOT EXISTS "idx_channel_connections_marketplace_integration_id" 
ON "public"."channel_connections" ("marketplace_integration_id") 
WHERE "is_active" = true;
