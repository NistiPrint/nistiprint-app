-- Adiciona coluna de status para controle de concorrência no processamento de estoque
ALTER TABLE "public"."itens_demanda" 
ADD COLUMN IF NOT EXISTS "status_processamento" character varying(50) DEFAULT 'PENDENTE'::character varying;

-- Cria índice para performance da consulta de lock
CREATE INDEX IF NOT EXISTS "idx_itens_demanda_status_processamento" ON "public"."itens_demanda" ("status_processamento");
