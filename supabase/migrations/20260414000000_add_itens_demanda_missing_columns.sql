-- Migration: 20260414000000_add_itens_demanda_missing_columns
-- Data: 2026-04-14
-- Propósito: Adicionar colunas faltantes em itens_demanda para suportar auto-consolidação de pedidos
-- Colunas: quantidade_planejada, sku_externo

-- ============================================================
-- 1. ADICIONAR COLUNA quantidade_planejada
-- ============================================================
-- Esta coluna é usada pelo worker de auto-consolidação para rastrear
-- a quantidade planejada vs quantidade realizada
ALTER TABLE public.itens_demanda 
ADD COLUMN IF NOT EXISTS quantidade_planejada NUMERIC(15,4);

-- ============================================================
-- 2. ADICIONAR COLUNA sku_externo
-- ============================================================
-- Esta coluna é usada para mapear itens de demanda com SKUs externos
-- (por exemplo, SKUs do Bling, Shopee, etc.)
ALTER TABLE public.itens_demanda 
ADD COLUMN IF NOT EXISTS sku_externo VARCHAR(255);

-- ============================================================
-- 3. POPULAR DADOS EXISTENTES
-- ============================================================
-- Para registros existentes, copiar valores das colunas equivalentes
-- Isso garante consistência para dados já criados

UPDATE public.itens_demanda 
SET quantidade_planejada = quantidade 
WHERE quantidade_planejada IS NULL 
  AND quantidade IS NOT NULL;

UPDATE public.itens_demanda 
SET sku_externo = sku 
WHERE sku_externo IS NULL 
  AND sku IS NOT NULL;

-- ============================================================
-- 4. COMENTÁRIOS PARA DOCUMENTAÇÃO
-- ============================================================
COMMENT ON COLUMN public.itens_demanda.quantidade_planejada IS 
'Quantidade planejada para produção (diferente de quantidade que é a quantidade realizada/concluída)';

COMMENT ON COLUMN public.itens_demanda.sku_externo IS 
'SKU externo (por exemplo, do Bling, Shopee, etc.) para mapeamento com sistemas externos';
