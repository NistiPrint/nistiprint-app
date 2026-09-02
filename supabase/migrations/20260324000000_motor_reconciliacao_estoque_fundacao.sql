-- Migration: motor_reconciliacao_estoque_fundacao
-- Data: 2026-03-24
-- Propósito: Fundação do Motor de Reconciliação de Estoque
-- Implementa: tipo_produto, eventos_producao, e melhorias no ledger

-- ============================================================
-- 1. CRIAR ENUM TIPO_PRODUTO
-- ============================================================

-- Criar enum para classificação de produtos
DO $$ BEGIN
    CREATE TYPE public.tipo_produto_enum AS ENUM (
        'MATERIA_PRIMA',
        'INTERMEDIARIO',
        'PRODUTO_ACABADO'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Adicionar coluna tipo_produto na tabela produtos
ALTER TABLE public.produtos 
ADD COLUMN IF NOT EXISTS tipo_produto public.tipo_produto_enum DEFAULT 'MATERIA_PRIMA';

-- Criar índice para filtragem por tipo
CREATE INDEX IF NOT EXISTS idx_produtos_tipo_produto ON public.produtos(tipo_produto);

-- Comentário para documentação
COMMENT ON COLUMN public.produtos.tipo_produto IS 
'Classificação do produto: MATERIA_PRIMA (pode ficar negativo), INTERMEDIARIO (nunca negativo), PRODUTO_ACABADO (nunca negativo)';

-- ============================================================
-- 2. CRIAR TABELA EVENTOS_PRODUCAO (SINAIS VISUAIS)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.eventos_producao (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_demanda_id INTEGER NOT NULL REFERENCES public.itens_demanda(id) ON DELETE CASCADE,
    demanda_id INTEGER NOT NULL REFERENCES public.demandas_producao(id) ON DELETE CASCADE,
    estagio VARCHAR(50) NOT NULL, -- 'capas_impressas_qtd', 'capas_produzidas_qtd', etc.
    quantidade_reportada DECIMAL(15,4) NOT NULL DEFAULT 0, -- Valor reportado pelo usuário
    quantidade_efetiva DECIMAL(15,4), -- Valor calculado pelo motor (waterfall top-down)
    tipo_evento VARCHAR(20) NOT NULL DEFAULT 'SINAL', -- 'SINAL' (E1-E6) ou 'LIQUIDACAO' (E7)
    processado BOOLEAN NOT NULL DEFAULT false, -- Se já foi processado pelo motor
    correlation_id VARCHAR(100), -- Para idempotência e rastreabilidade
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_eventos_producao_item ON public.eventos_producao(item_demanda_id);
CREATE INDEX IF NOT EXISTS idx_eventos_producao_demanda ON public.eventos_producao(demanda_id);
CREATE INDEX IF NOT EXISTS idx_eventos_producao_estagio ON public.eventos_producao(estagio);
CREATE INDEX IF NOT EXISTS idx_eventos_producao_tipo ON public.eventos_producao(tipo_evento);
CREATE INDEX IF NOT EXISTS idx_eventos_producao_processado 
    ON public.eventos_producao(processado) WHERE processado = false;
CREATE INDEX IF NOT EXISTS idx_eventos_producao_correlation 
    ON public.eventos_producao(correlation_id);

-- Índice único para prevenir duplicação (idempotência)
CREATE UNIQUE INDEX IF NOT EXISTS idx_eventos_unique_item_estagio_correlation 
    ON public.eventos_producao(item_demanda_id, estagio, correlation_id)
    WHERE tipo_evento = 'SINAL';

-- Trigger para updated_at (usando a função existente)
DROP TRIGGER IF EXISTS update_eventos_producao_modtime ON public.eventos_producao;
CREATE TRIGGER update_eventos_producao_modtime
    BEFORE UPDATE ON public.eventos_producao
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_column();

-- Comentário para documentação
COMMENT ON TABLE public.eventos_producao IS 
'Registra sinais visuais de progresso (E1-E6) e eventos de liquidação (E7). Sinais NÃO consomem estoque, apenas registram intenção.';

-- ============================================================
-- 3. MODIFICAR LEDGER (DEMANDA_ESTOQUE_PROCESSADO)
-- ============================================================

-- Adicionar coluna tipo_movimentacao
ALTER TABLE public.demanda_estoque_processado
ADD COLUMN IF NOT EXISTS tipo_movimentacao VARCHAR(50) NOT NULL DEFAULT 'CONS_MP';

-- Adicionar constraint CHECK para tipos válidos
ALTER TABLE public.demanda_estoque_processado
DROP CONSTRAINT IF EXISTS check_tipo_movimentacao;

ALTER TABLE public.demanda_estoque_processado
ADD CONSTRAINT check_tipo_movimentacao 
CHECK (tipo_movimentacao IN (
    'CONS_MP',      -- Consumo de Matéria Prima
    'PROD_INT',     -- Produção de Intermediário (auto-produção)
    'CONS_INT',     -- Consumo de Intermediário
    'PROD_ACAB',    -- Produção de Acabado
    'RESERVA',      -- Reserva de estoque
    'LIB_RESERVA',  -- Liberação de reserva
    'AJUSTE',       -- Ajuste de inventário
    'ESTORNO'       -- Estorno de movimentação
));

-- Adicionar coluna produto_id para rastreabilidade direta
ALTER TABLE public.demanda_estoque_processado
ADD COLUMN IF NOT EXISTS produto_id INTEGER REFERENCES public.produtos(id);

-- Criar índice para produto_id
CREATE INDEX IF NOT EXISTS idx_estoque_proc_produto ON public.demanda_estoque_processado(produto_id);

-- Adicionar coluna usuario_id para auditoria
ALTER TABLE public.demanda_estoque_processado
ADD COLUMN IF NOT EXISTS usuario_id INTEGER REFERENCES public.usuarios(id);

-- Adicionar coluna metadata para informações adicionais
ALTER TABLE public.demanda_estoque_processado
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- Comentário para documentação
COMMENT ON COLUMN public.demanda_estoque_processado.tipo_movimentacao IS 
'Tipo de movimentação: CONS_MP (consumo MP), PROD_INT (produção intermediária), CONS_INT (consumo intermediário), PROD_ACAB (produção acabado), RESERVA, LIB_RESERVA, AJUSTE, ESTORNO';

-- ============================================================
-- 4. CRIAR ÍNDICES COMPOSTOS NO LEDGER
-- ============================================================

-- Índice único para idempotência (previne duplicação por correlation_id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_unique_correlation 
    ON public.demanda_estoque_processado(item_id, estagio, correlation_id)
    WHERE correlation_id IS NOT NULL;

-- Índice composto para consultas de auditoria por demanda
CREATE INDEX IF NOT EXISTS idx_ledger_demanda_estagio 
    ON public.demanda_estoque_processado(demanda_id, estagio);

-- Índice composto para consultas de saldo acumulado
CREATE INDEX IF NOT EXISTS idx_ledger_item_estagio_created 
    ON public.demanda_estoque_processado(item_id, estagio, created_at);

-- ============================================================
-- 5. CRIAR VIEW PARA AUDITORIA (LEDGER COMPLETO)
-- ============================================================

CREATE OR REPLACE VIEW public.view_ledger_completo AS
SELECT 
    dep.id,
    dep.item_id,
    id.descricao as item_descricao,
    id.sku as item_sku,
    dp.id as demanda_id,
    dp.descricao as demanda_descricao,
    dep.estagio,
    dep.tipo_movimentacao,
    dep.produto_id,
    p.nome as produto_nome,
    p.sku as produto_sku,
    p.tipo_produto,
    dep.quantidade,
    dep.saldo_acumulado,
    dep.correlation_id,
    dep.usuario_id,
    u.nome as usuario_responsavel,
    dep.metadata,
    dep.created_at,
    dep.updated_at
FROM public.demanda_estoque_processado dep
JOIN public.itens_demanda id ON dep.item_id = id.id
JOIN public.demandas_producao dp ON dep.demanda_id = dp.id
LEFT JOIN public.produtos p ON dep.produto_id = p.id
LEFT JOIN public.usuarios u ON dep.usuario_id = u.id
ORDER BY dep.created_at DESC;

-- Comentário para documentação
COMMENT ON VIEW public.view_ledger_completo IS 
'View consolidada do ledger de estoque para auditoria. Mostra todas as movimentações com detalhes de demanda, item, produto e usuário.';

-- ============================================================
-- 6. CRIAR FUNÇÃO DE RASTREABILIDADE
-- ============================================================

CREATE OR REPLACE FUNCTION public.get_ledger_por_item_demanda(
    p_item_id INTEGER,
    p_demanda_id INTEGER
)
RETURNS TABLE (
    id UUID,
    estagio VARCHAR,
    tipo_movimentacao VARCHAR,
    produto_id INTEGER,
    produto_nome VARCHAR,
    quantidade DECIMAL,
    saldo_acumulado DECIMAL,
    correlation_id VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        dep.id,
        dep.estagio,
        dep.tipo_movimentacao,
        dep.produto_id,
        p.nome as produto_nome,
        dep.quantidade,
        dep.saldo_acumulado,
        dep.correlation_id,
        dep.created_at
    FROM public.demanda_estoque_processado dep
    LEFT JOIN public.produtos p ON dep.produto_id = p.id
    WHERE dep.item_id = p_item_id 
      AND dep.demanda_id = p_demanda_id
    ORDER BY dep.created_at ASC;
END;
$$ LANGUAGE plpgsql STABLE;

-- Comentário para documentação
COMMENT ON FUNCTION public.get_ledger_por_item_demanda IS 
'Retorna todo o histórico de movimentações de estoque para um item específico de uma demanda.';

-- ============================================================
-- 7. GRANT PERMISSIONS
-- ============================================================

-- Eventos de produção
GRANT ALL ON public.eventos_producao TO postgres;
GRANT ALL ON public.eventos_producao TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.eventos_producao TO authenticated;

-- Ledger (demanda_estoque_processado) - já existente, mas reforçar
GRANT ALL ON public.demanda_estoque_processado TO postgres;
GRANT ALL ON public.demanda_estoque_processado TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.demanda_estoque_processado TO authenticated;

-- View
GRANT SELECT ON public.view_ledger_completo TO postgres;
GRANT SELECT ON public.view_ledger_completo TO service_role;
GRANT SELECT ON public.view_ledger_completo TO authenticated;

-- Função
GRANT EXECUTE ON FUNCTION public.get_ledger_por_item_demanda TO postgres;
GRANT EXECUTE ON FUNCTION public.get_ledger_por_item_demanda TO service_role;
GRANT EXECUTE ON FUNCTION public.get_ledger_por_item_demanda TO authenticated;

-- ============================================================
-- 8. MIGRAÇÃO DE DADOS (OPCIONAL - POPULAR TIPO_PRODUTO)
-- ============================================================

-- Atualizar produtos baseados na categoria (heurística)
-- MATERIA_PRIMA: categorias com 'matéria', 'insumo', 'material'
UPDATE public.produtos p
SET tipo_produto = 'MATERIA_PRIMA'
FROM public.categorias c
WHERE p.categoria_id = c.id 
AND (
    c.nome ILIKE '%matéria%prima%' OR 
    c.nome ILIKE '%materia%prima%' OR
    c.nome ILIKE '%insumo%' OR 
    c.nome ILIKE '%material%' OR
    c.nome ILIKE '%sulfite%' OR
    c.nome ILIKE '%tinta%' OR
    c.nome ILIKE '%adesivo%' OR
    c.nome ILIKE '%papelao%' OR
    c.nome ILIKE '%espiral%' OR
    c.nome ILIKE '%embalagem%'
)
AND p.tipo_produto IS NULL;

-- INTERMEDIARIO: categorias com 'intermediário', 'capa', 'miolo', 'semiacabado'
UPDATE public.produtos p
SET tipo_produto = 'INTERMEDIARIO'
FROM public.categorias c
WHERE p.categoria_id = c.id 
AND (
    c.nome ILIKE '%intermediário%' OR
    c.nome ILIKE '%intermediario%' OR
    c.nome ILIKE '%capa%' OR
    c.nome ILIKE '%miolo%' OR
    c.nome ILIKE '%semiacabado%' OR
    c.nome ILIKE '%semi-acabado%'
)
AND p.tipo_produto IS NULL;

-- PRODUTO_ACABADO: categorias com 'acabado', 'agenda', 'caderno', 'bloco'
UPDATE public.produtos p
SET tipo_produto = 'PRODUTO_ACABADO'
FROM public.categorias c
WHERE p.categoria_id = c.id 
AND (
    c.nome ILIKE '%acabado%' OR
    c.nome ILIKE '%agenda%' OR
    c.nome ILIKE '%caderno%' OR
    c.nome ILIKE '%bloco%' OR
    c.nome ILIKE '%produto final%'
)
AND p.tipo_produto IS NULL;

-- ============================================================
-- FIM DA MIGRATION
-- ============================================================
