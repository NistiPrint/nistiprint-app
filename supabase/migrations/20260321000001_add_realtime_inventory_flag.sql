-- Migration: add_realtime_inventory_flag
-- Data: 2026-03-21
-- Propósito: Adicionar flag para controlar se o estoque da categoria é processado em tempo real (JIT) ou na finalização

ALTER TABLE "public"."categorias" 
ADD COLUMN IF NOT EXISTS "realtime_inventory" BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN "public"."categorias"."realtime_inventory" IS 'Se TRUE, o estoque dos produtos desta categoria é processado em tempo real durante as etapas de produção. Se FALSE (padrão), é processado apenas na finalização do item via explosão de BOM.';

-- Atualizar categoria 'Miolos' para realtime (assumindo que existe uma categoria com nome contendo 'Miolo')
UPDATE "public"."categorias"
SET "realtime_inventory" = TRUE
WHERE "nome" ILIKE '%Miolo%';
