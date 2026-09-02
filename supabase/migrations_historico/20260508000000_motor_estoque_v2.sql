-- Migration: motor_estoque_v2
-- Data: 2026-05-08
-- Propósito: Implementação do Motor de Estoque v2 — Reconciliação Síncrona com Produção JIT

-- 1. Adicionar campos à tabela movimentacoes_estoque
ALTER TABLE public.movimentacoes_estoque
ADD COLUMN IF NOT EXISTS is_jit BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS coluna_origem VARCHAR(50),
ADD COLUMN IF NOT EXISTS lote_id UUID,
ADD COLUMN IF NOT EXISTS parent_movimento_id INTEGER REFERENCES public.movimentacoes_estoque(id),
ADD COLUMN IF NOT EXISTS item_demanda_id INTEGER REFERENCES public.itens_demanda(id);

-- 2. Criar índices para performance da reconciliação
CREATE INDEX IF NOT EXISTS idx_movimentacoes_estoque_lote_id ON public.movimentacoes_estoque(lote_id);
CREATE INDEX IF NOT EXISTS idx_movimentacoes_estoque_item_demanda_id ON public.movimentacoes_estoque(item_demanda_id);
CREATE INDEX IF NOT EXISTS idx_movimentacoes_estoque_jit_item_demanda 
  ON public.movimentacoes_estoque (item_demanda_id, produto_id, is_jit);

-- 3. Adicionar comentário para documentação
COMMENT ON COLUMN public.movimentacoes_estoque.is_jit IS 'Indica se a movimentação é de produção JIT (compensatória)';
COMMENT ON COLUMN public.movimentacoes_estoque.coluna_origem IS 'Coluna do dashboard que originou a movimentação (E1-E7, etc)';
COMMENT ON COLUMN public.movimentacoes_estoque.lote_id IS 'ID do lote para garantir idempotência do processamento';
COMMENT ON COLUMN public.movimentacoes_estoque.parent_movimento_id IS 'Link entre produção JIT e seus consumos de componentes associados';
COMMENT ON COLUMN public.movimentacoes_estoque.item_demanda_id IS 'Link direto com o item de demanda para reconciliação incremental';
