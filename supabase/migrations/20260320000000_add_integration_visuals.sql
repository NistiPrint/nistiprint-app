-- Migration para adicionar campos descritivos nas integrações instaladas
-- Objetivo: Permitir que o usuário identifique visualmente cada instância (ex: "Shopee Principal" vs "Shopee Outlet")
-- Data: 2026-03-20

ALTER TABLE "public"."installed_integrations" 
ADD COLUMN IF NOT EXISTS "instance_color" VARCHAR(20) DEFAULT '#64748b', -- Cor hexadecimal para badges
ADD COLUMN IF NOT EXISTS "description" TEXT; -- Descrição opcional (ex: "Conta usada para queima de estoque")

-- Comentários para documentação
COMMENT ON COLUMN "public"."installed_integrations"."instance_color" IS 'Cor hexadecimal para identificação visual da instância na UI';
COMMENT ON COLUMN "public"."installed_integrations"."description" IS 'Descrição opcional do propósito desta instância de integração';
