-- ============================================
-- Tabela de Configuração de Vínculos de Integração
-- ============================================
-- Permite vincular canais de venda internos com:
-- - Lojas específicas no Bling (bling_loja_id)
-- - Instâncias de integração (installed_integrations)
-- - Plataformas (Shopee, Amazon, etc.)
-- ============================================

CREATE TABLE IF NOT EXISTS "public"."integracao_canais_config" (
    "id" uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    "canal_venda_id" integer REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE,
    "integration_id" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL,
    "bling_loja_id" bigint,
    "plataforma_nome" character varying(100),
    "is_active" boolean DEFAULT true,
    "is_primary" boolean DEFAULT false,
    "config_json" jsonb DEFAULT '{}'::jsonb,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    
    -- Um canal não pode ter dois vínculos para a mesma loja Bling
    UNIQUE("canal_venda_id", "bling_loja_id"),
    
    -- Uma integração não pode ter dois vínculos para a mesma loja Bling
    UNIQUE("integration_id", "bling_loja_id")
);

-- Índice para busca rápida por bling_loja_id (usado em webhooks)
CREATE INDEX IF NOT EXISTS "idx_integracao_canais_bling_loja_id" 
ON "public"."integracao_canais_config"("bling_loja_id") 
WHERE "is_active" = true;

-- Índice para busca por canal
CREATE INDEX IF NOT EXISTS "idx_integracao_canais_canal_id" 
ON "public"."integracao_canais_config"("canal_venda_id") 
WHERE "is_active" = true;

-- Índice para busca por plataforma
CREATE INDEX IF NOT EXISTS "idx_integracao_canais_plataforma" 
ON "public"."integracao_canais_config"("plataforma_nome") 
WHERE "is_active" = true;

-- Trigger para atualizar updated_at
CREATE OR REPLACE TRIGGER "update_integracao_canais_config_updated_at"
BEFORE UPDATE ON "public"."integracao_canais_config"
FOR EACH ROW
EXECUTE FUNCTION "public"."update_updated_at_column"();

-- ============================================
-- Colunas de fallback em canais_venda
-- ============================================
-- Para compatibilidade com código legado e fallback rápido

ALTER TABLE "public"."canais_venda" 
ADD COLUMN IF NOT EXISTS "bling_loja_id_principal" bigint,
ADD COLUMN IF NOT EXISTS "integration_id_principal" integer REFERENCES "public"."installed_integrations"("id") ON DELETE SET NULL;

-- Índice para busca rápida
CREATE INDEX IF NOT EXISTS "idx_canais_venda_bling_loja_id" 
ON "public"."canais_venda"("bling_loja_id_principal") 
WHERE "bling_loja_id_principal" IS NOT NULL;

-- ============================================
-- Comentários de documentação
-- ============================================

COMMENT ON TABLE "public"."integracao_canais_config" IS 
'Configuração de vínculos entre canais de venda internos, lojas Bling e instâncias de integração';

COMMENT ON COLUMN "public"."integracao_canais_config"."canal_venda_id" IS 
'Referência ao canal de venda interno (ex: Shopee, Amazon)';

COMMENT ON COLUMN "public"."integracao_canais_config"."integration_id" IS 
'Referência à instância de integração em installed_integrations';

COMMENT ON COLUMN "public"."integracao_canais_config"."bling_loja_id" IS 
'ID da loja no Bling (ex: 204047801, 205218967 para Shopee)';

COMMENT ON COLUMN "public"."integracao_canais_config"."plataforma_nome" IS 
'Nome da plataforma: shopee, amazon, mercadolivre, shein';

COMMENT ON COLUMN "public"."integracao_canais_config"."is_primary" IS 
'Indica se este é o vínculo principal para a plataforma (útil para múltiplas lojas)';

COMMENT ON COLUMN "public"."integracao_canais_config"."config_json" IS 
'Configurações adicionais específicas do vínculo';

COMMENT ON COLUMN "public"."canais_venda"."bling_loja_id_principal" IS 
'ID da loja Bling principal para este canal (fallback)';

COMMENT ON COLUMN "public"."canais_venda"."integration_id_principal" IS 
'ID da integração principal para este canal (fallback)';

-- ============================================
-- Permissões (RLS desativado para tabela de configuração)
-- ============================================

ALTER TABLE "public"."integracao_canais_config" DISABLE ROW LEVEL SECURITY;

-- Grants padrão
GRANT ALL ON TABLE "public"."integracao_canais_config" TO "anon";
GRANT ALL ON TABLE "public"."integracao_canais_config" TO "authenticated";
GRANT ALL ON TABLE "public"."integracao_canais_config" TO "service_role";

-- ============================================
-- Dados iniciais (populado com base em BLING_ID_LOJA dos constants.py)
-- ============================================

-- Nota: Os dados serão populados via script Python para garantir consistência
-- com as configurações existentes no sistema.
-- Este script deve ser executado após o deploy desta migration.

-- Estrutura esperada dos dados iniciais:
-- Shopee (antiga): canal_id=1, bling_loja_id=204047801
-- Shopee (nova): canal_id=1, bling_loja_id=205218967
-- Amazon (nova): canal_id=8, bling_loja_id=203726842
-- Amazon (nova conta): canal_id=8, bling_loja_id=205228669
-- MercadoLivre: canal_id=9, bling_loja_id=203753446
-- Shein: canal_id=7, bling_loja_id=204698686
-- Shein (cnpj03): canal_id=7, bling_loja_id=205533791
