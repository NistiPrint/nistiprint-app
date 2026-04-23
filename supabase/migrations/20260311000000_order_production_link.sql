-- Migração para vincular Pedidos e Demandas de Produção
-- Data: 2026-03-11

-- 1. Adicionar coluna de vínculo em demandas_producao
ALTER TABLE "public"."demandas_producao" 
ADD COLUMN IF NOT EXISTS "pedido_id" integer REFERENCES "public"."pedidos"("id") ON DELETE SET NULL;

COMMENT ON COLUMN "public"."demandas_producao"."pedido_id" IS 'Vínculo direto com a entidade unificada de pedidos.';

-- 2. Garantir que a plataforma 'Bling' existe para fins de configuração de integração
INSERT INTO "public"."plataformas" ("nome", "tipo", "ativa", "configuracao")
VALUES ('Bling', 'ERP', true, '{"order_id_field": "numeroLoja", "display_name": "Bling ERP"}')
ON CONFLICT ("nome") DO UPDATE 
SET "configuracao" = EXCLUDED.configuracao;

-- 3. Atualizar configurações das plataformas existentes com o campo de ID único
UPDATE "public"."plataformas" 
SET "configuracao" = jsonb_set(COALESCE("configuracao", '{}'::jsonb), '{order_id_field}', '"order_sn"')
WHERE "nome" = 'Shopee';

UPDATE "public"."plataformas" 
SET "configuracao" = jsonb_set(COALESCE("configuracao", '{}'::jsonb), '{order_id_field}', '"id"')
WHERE "nome" = 'Mercado Livre';

UPDATE "public"."plataformas" 
SET "configuracao" = jsonb_set(COALESCE("configuracao", '{}'::jsonb), '{order_id_field}', '"order-id"')
WHERE "nome" = 'Amazon';

-- 4. Criar um índice para busca rápida de vínculos
CREATE INDEX IF NOT EXISTS "idx_demandas_producao_pedido_id" ON "public"."demandas_producao" ("pedido_id");
