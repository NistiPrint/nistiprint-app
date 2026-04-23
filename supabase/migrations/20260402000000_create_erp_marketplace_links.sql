-- ============================================
-- Migration: ERP Marketplace Links
-- ============================================
-- Cria tabela para vínculos entre instâncias ERP (ex: Bling) 
-- e instâncias de Marketplace, com ID da loja no ERP
-- ============================================

-- 1. Criar tabela erp_marketplace_links
CREATE TABLE IF NOT EXISTS "public"."erp_marketplace_links" (
    "id" uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    
    -- Instância do ERP (ex: Bling)
    "erp_integration_id" integer NOT NULL REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE,
    
    -- Instância do Marketplace (ex: Shopee)
    "marketplace_integration_id" integer NOT NULL REFERENCES "public"."installed_integrations"("id") ON DELETE CASCADE,
    
    -- ID da loja no ERP (ex: loja_id no Bling)
    "erp_store_id" varchar(100) NOT NULL,
    
    -- Nome amigável (ex: "Shopee Antiga")
    "store_name" varchar(255),
    
    -- Configurações específicas (opcional)
    "config" jsonb DEFAULT '{}',
    
    -- Timestamps
    "created_at" timestamp with time zone DEFAULT now(),
    "updated_at" timestamp with time zone DEFAULT now(),
    
    -- Constraints
    UNIQUE ("erp_integration_id", "marketplace_integration_id"),
    UNIQUE ("erp_integration_id", "erp_store_id")
);

-- 2. Comentários de documentação
COMMENT ON TABLE "public"."erp_marketplace_links" IS 
  'Vínculo entre instância ERP (ex: Bling) e instâncias de Marketplace, com ID da loja no ERP';

COMMENT ON COLUMN "public"."erp_marketplace_links"."erp_integration_id" IS
  'Referência à instância de integração ERP (module_id=bling em installed_integrations)';

COMMENT ON COLUMN "public"."erp_marketplace_links"."marketplace_integration_id" IS
  'Referência à instância de integração de Marketplace (shopee, amazon, etc. em installed_integrations)';

COMMENT ON COLUMN "public"."erp_marketplace_links"."erp_store_id" IS
  'ID da loja dentro do ERP (ex: bling_loja_id = 204047801, 205218967)';

COMMENT ON COLUMN "public"."erp_marketplace_links"."store_name" IS
  'Nome amigável da loja (ex: "Shopee Antiga", "Shopee Nova")';

COMMENT ON COLUMN "public"."erp_marketplace_links"."config" IS
  'Configurações específicas deste vínculo (ex: id_campo_personalizado, mapeamentos)';

-- 3. Criar índices para performance
CREATE INDEX IF NOT EXISTS "idx_erp_links_erp_id" 
ON "public"."erp_marketplace_links"("erp_integration_id");

CREATE INDEX IF NOT EXISTS "idx_erp_links_marketplace_id" 
ON "public"."erp_marketplace_links"("marketplace_integration_id");

CREATE INDEX IF NOT EXISTS "idx_erp_links_store_id" 
ON "public"."erp_marketplace_links"("erp_store_id");

CREATE INDEX IF NOT EXISTS "idx_erp_links_composite" 
ON "public"."erp_marketplace_links"("erp_integration_id", "marketplace_integration_id");

-- 4. Trigger para atualizar updated_at
CREATE OR REPLACE TRIGGER "update_erp_marketplace_links_updated_at" 
BEFORE UPDATE ON "public"."erp_marketplace_links" 
FOR EACH ROW 
EXECUTE FUNCTION "public"."update_updated_at_column"();

-- 5. Grants de permissão
GRANT ALL ON TABLE "public"."erp_marketplace_links" TO "anon";
GRANT ALL ON TABLE "public"."erp_marketplace_links" TO "authenticated";
GRANT ALL ON TABLE "public"."erp_marketplace_links" TO "service_role";

-- 6. RLS Policies (Row Level Security)
ALTER TABLE "public"."erp_marketplace_links" ENABLE ROW LEVEL SECURITY;

-- Policy: Usuários autenticados podem ler todos os vínculos
CREATE POLICY "Usuários autenticados podem visualizar vínculos"
ON "public"."erp_marketplace_links"
FOR SELECT
TO authenticated
USING (true);

-- Policy: Apenas service_role pode inserir/atualizar/deletar (via API)
CREATE POLICY "Apenas service_role pode gerenciar vínculos"
ON "public"."erp_marketplace_links"
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);
