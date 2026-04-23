-- Migration to add finalizados_qtd to itens_demanda
-- Data: 2026-03-13

ALTER TABLE "public"."itens_demanda" 
ADD COLUMN IF NOT EXISTS "finalizados_qtd" NUMERIC(15,4) DEFAULT 0;

-- Update existing records to have a consistent state if needed
-- (Assuming for now that if status_item is 'Concluído', finalizados_qtd should be equal to quantidade)
UPDATE "public"."itens_demanda"
SET "finalizados_qtd" = "quantidade"
WHERE "status_item" = 'Concluído' AND "finalizados_qtd" = 0;
