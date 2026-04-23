-- Migration: Adicionar origem_demanda em demandas_producao
-- Data: 2026-04-02
-- Descrição: Identificar se demanda foi criada automaticamente (webhook/forçar) ou manualmente

-- Adicionar coluna
ALTER TABLE public.demandas_producao 
ADD COLUMN IF NOT EXISTS origem_demanda VARCHAR(20) DEFAULT 'MANUAL';

-- Adicionar check constraint
ALTER TABLE public.demandas_producao
ADD CONSTRAINT chk_origem_demanda 
CHECK (origem_demanda IN ('AUTOMATICA', 'MANUAL'));

-- Adicionar comentário
COMMENT ON COLUMN public.demandas_producao.origem_demanda IS 
'Origem da demanda: AUTOMATICA (webhook/forçar consolidação) ou MANUAL (criada pelo usuário)';

-- Criar índice para filtragem
CREATE INDEX IF NOT EXISTS idx_demandas_origem 
ON public.demandas_producao(origem_demanda) 
WHERE status = 'RASCUNHO';

-- Atualizar rascunhos existentes para 'MANUAL' (default)
UPDATE public.demandas_producao 
SET origem_demanda = 'MANUAL' 
WHERE origem_demanda IS NULL;
