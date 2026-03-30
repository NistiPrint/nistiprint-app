-- Migration: fix_demanda_alocacoes_tipo_alocacao
-- Data: 2026-03-21
-- Propósito: Adicionar tipos PREVISAO_ESTOQUE e PREVISAO_PRODUCAO_JIT à constraint chk_tipo_alocacao

-- Drop da constraint antiga
ALTER TABLE "public"."demanda_alocacoes_estoque"
DROP CONSTRAINT IF EXISTS chk_tipo_alocacao;

-- Recriar constraint com os novos valores
ALTER TABLE "public"."demanda_alocacoes_estoque"
ADD CONSTRAINT chk_tipo_alocacao 
CHECK (tipo_alocacao IN (
    'MANUAL_DASHBOARD', 
    'FINALIZACAO', 
    'PRODUCAO_JIT', 
    'SAIDA_DISTRIBUIDA',
    'PREVISAO_ESTOQUE',
    'PREVISAO_PRODUCAO_JIT'
));
