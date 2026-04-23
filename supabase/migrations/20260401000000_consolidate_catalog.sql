-- ============================================
-- Migration: Consolidação do Catálogo de Integrações
-- ============================================
-- Unifica plataformas em integration_modules
-- Adiciona campos: tipo, slug, is_aggregator
-- ============================================

-- 1. Adicionar novos campos em integration_modules
ALTER TABLE "public"."integration_modules"
ADD COLUMN IF NOT EXISTS "tipo" varchar(50),  -- 'MARKETPLACE', 'ERP', 'ECOMMERCE'
ADD COLUMN IF NOT EXISTS "slug" varchar(100),
ADD COLUMN IF NOT EXISTS "is_aggregator" boolean DEFAULT false;

-- 2. Adicionar índice único em slug
CREATE UNIQUE INDEX IF NOT EXISTS "idx_integration_modules_slug" 
ON "public"."integration_modules"("slug") 
WHERE "slug" IS NOT NULL;

-- 3. Migrar dados de plataformas para integration_modules
-- Shopee
INSERT INTO "public"."integration_modules" (id, name, tipo, slug, is_aggregator, is_active, created_at, updated_at)
SELECT 
  'shopee' as id,
  'Shopee' as name,
  'MARKETPLACE' as tipo,
  'shopee' as slug,
  false as is_aggregator,
  true as is_active,
  NOW() as created_at,
  NOW() as updated_at
WHERE NOT EXISTS (SELECT 1 FROM integration_modules WHERE id = 'shopee');

-- Mercado Livre
INSERT INTO "public"."integration_modules" (id, name, tipo, slug, is_aggregator, is_active, created_at, updated_at)
SELECT 
  'mercadolivre' as id,
  'Mercado Livre' as name,
  'MARKETPLACE' as tipo,
  'mercadolivre' as slug,
  false as is_aggregator,
  true as is_active,
  NOW() as created_at,
  NOW() as updated_at
WHERE NOT EXISTS (SELECT 1 FROM integration_modules WHERE id = 'mercadolivre');

-- Amazon
INSERT INTO "public"."integration_modules" (id, name, tipo, slug, is_aggregator, is_active, created_at, updated_at)
SELECT 
  'amazon' as id,
  'Amazon' as name,
  'MARKETPLACE' as tipo,
  'amazon' as slug,
  false as is_aggregator,
  true as is_active,
  NOW() as created_at,
  NOW() as updated_at
WHERE NOT EXISTS (SELECT 1 FROM integration_modules WHERE id = 'amazon');

-- Shein
INSERT INTO "public"."integration_modules" (id, name, tipo, slug, is_aggregator, is_active, created_at, updated_at)
SELECT 
  'shein' as id,
  'Shein' as name,
  'MARKETPLACE' as tipo,
  'shein' as slug,
  false as is_aggregator,
  true as is_active,
  NOW() as created_at,
  NOW() as updated_at
WHERE NOT EXISTS (SELECT 1 FROM integration_modules WHERE id = 'shein');

-- TikTok Shop
INSERT INTO "public"."integration_modules" (id, name, tipo, slug, is_aggregator, is_active, created_at, updated_at)
SELECT 
  'tiktokshop' as id,
  'TikTok Shop' as name,
  'MARKETPLACE' as tipo,
  'tiktokshop' as slug,
  false as is_aggregator,
  true as is_active,
  NOW() as created_at,
  NOW() as updated_at
WHERE NOT EXISTS (SELECT 1 FROM integration_modules WHERE id = 'tiktokshop');

-- Bling (ERP - Aggregator)
INSERT INTO "public"."integration_modules" (id, name, tipo, slug, is_aggregator, is_active, created_at, updated_at)
SELECT 
  'bling' as id,
  'Bling' as name,
  'ERP' as tipo,
  'bling' as slug,
  true as is_aggregator,
  true as is_active,
  NOW() as created_at,
  NOW() as updated_at
WHERE NOT EXISTS (SELECT 1 FROM integration_modules WHERE id = 'bling');

-- Loja Integrada
INSERT INTO "public"."integration_modules" (id, name, tipo, slug, is_aggregator, is_active, created_at, updated_at)
SELECT 
  'lojaintegrada' as id,
  'Loja Integrada' as name,
  'ECOMMERCE' as tipo,
  'lojaintegrada' as slug,
  false as is_aggregator,
  true as is_active,
  NOW() as created_at,
  NOW() as updated_at
WHERE NOT EXISTS (SELECT 1 FROM integration_modules WHERE id = 'lojaintegrada');

-- 4. Atualizar integration_modules existentes com tipo e slug
UPDATE "public"."integration_modules" 
SET 
  tipo = CASE 
    WHEN id IN ('shopee', 'mercadolivre', 'amazon', 'shein', 'tiktokshop') THEN 'MARKETPLACE'
    WHEN id = 'bling' THEN 'ERP'
    WHEN id = 'lojaintegrada' THEN 'ECOMMERCE'
    ELSE tipo
  END,
  slug = COALESCE(slug, LOWER(REPLACE(id, ' ', ''))),
  is_aggregator = CASE WHEN id = 'bling' THEN true ELSE is_aggregator END
WHERE slug IS NULL OR tipo IS NULL;

-- 5. Atualizar installed_integrations com platform_slug
ALTER TABLE "public"."installed_integrations"
ADD COLUMN IF NOT EXISTS "platform_slug" varchar(100);

-- Criar índice para performance
CREATE INDEX IF NOT EXISTS "idx_installed_integrations_platform_slug" 
ON "public"."installed_integrations"("platform_slug");

-- Migrar module_id para platform_slug
UPDATE "public"."installed_integrations"
SET platform_slug = LOWER(REPLACE(module_id, ' ', ''))
WHERE platform_slug IS NULL;

-- 6. Adicionar foreign key para platform_slug (opcional, após validação)
-- ALTER TABLE "public"."installed_integrations"
-- ADD CONSTRAINT fk_installed_integrations_platform_slug
-- FOREIGN KEY (platform_slug) REFERENCES "public"."integration_modules"("slug");

-- 7. Comentários de documentação
COMMENT ON COLUMN "public"."integration_modules"."tipo" IS 'Tipo de plataforma: MARKETPLACE, ERP, ECOMMERCE';
COMMENT ON COLUMN "public"."integration_modules"."slug" IS 'Identificador único URL-friendly da plataforma';
COMMENT ON COLUMN "public"."integration_modules"."is_aggregator" IS 'True se a plataforma é um agregador (ex: Bling, ERPs)';
COMMENT ON COLUMN "public"."installed_integrations"."platform_slug" IS 'Referência ao slug da plataforma em integration_modules';

-- 8. Criar view de compatibilidade para plataformas (caso ainda exista código legado)
-- Esta view será removida na Fase 6
CREATE OR REPLACE VIEW "public"."plataformas_compat" AS
SELECT
  ROW_NUMBER() OVER (ORDER BY slug) as id,
  name as nome,
  NULL as descricao,
  tipo,
  is_active as ativa,
  config_schema as configuracao,
  created_at,
  updated_at
FROM "public"."integration_modules"
WHERE is_active = true;

-- Grant para a view
GRANT ALL ON TABLE "public"."plataformas_compat" TO "anon";
GRANT ALL ON TABLE "public"."plataformas_compat" TO "authenticated";
GRANT ALL ON TABLE "public"."plataformas_compat" TO "service_role";
