-- Migration: Regras Consolidação Canal
-- Created: 2026-04-02
--
-- Objetivo: Criar tabela de configuração de consolidação de pedidos por canal.
-- Permite ajustar critérios de agrupamento sem deploy de código.
--
-- Problema resolvido: Critérios de consolidação (janela de agrupamento, 
-- agrupar por produto/miolo, etc.) estavam hardcoded no código.

-- ============================================================================
-- 1. CRIAR TABELA regras_consolidacao_canal
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.regras_consolidacao_canal (
    id BIGSERIAL PRIMARY KEY,
    canal_venda_id BIGINT REFERENCES public.canais_venda(id) ON DELETE CASCADE,
    
    -- Modalidade a qual a regra se aplica (NULL = todas as modalidades)
    modalidade VARCHAR(50),
    
    -- Janela de agrupamento: pedidos dentro de X horas são agrupáveis
    janela_agrupamento_horas INTEGER DEFAULT 4,
    
    -- Critérios de agrupamento
    agrupar_por_produto BOOLEAN DEFAULT true,
    agrupar_por_miolo BOOLEAN DEFAULT true,
    agrupar_por_data_entrega BOOLEAN DEFAULT true,
    
    -- Comportamento quando demanda já existe para o grupo
    -- ADICIONAR: adiciona pedidos à demanda existente
    -- CRIAR_NOVA: sempre cria nova demanda
    comportamento_demanda_existente VARCHAR(20) DEFAULT 'ADICIONAR',
    
    -- Política de consolidação (timing)
    -- POR_EVENTO: consolida imediatamente ao receber pedido
    -- POR_JANELA: consolida em lotes de X em X minutos
    politica_consolidacao VARCHAR(20) DEFAULT 'POR_EVENTO',
    
    -- Intervalo de consideração para política POR_JANELA (em minutos)
    intervalo_consideracao_minutos INTEGER DEFAULT 15,
    
    -- Descrição opcional para documentação interna
    descricao TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Garante que não haja duplicatas para mesma combinação
    CONSTRAINT uq_canal_modalidade_consolidacao UNIQUE (canal_venda_id, modalidade)
);

-- ============================================================================
-- 2. ÍNDICES PARA PERFORMANCE
-- ============================================================================

-- Índice para busca por canal
CREATE INDEX IF NOT EXISTS idx_regras_consolidacao_canal_id
    ON public.regras_consolidacao_canal(canal_venda_id)
    WHERE modalidade IS NOT NULL;

-- Índice para busca por canal + modalidade
CREATE INDEX IF NOT EXISTS idx_regras_consolidacao_canal_modalidade
    ON public.regras_consolidacao_canal(canal_venda_id, modalidade);

-- Índice para regras gerais (modalidade NULL)
CREATE INDEX IF NOT EXISTS idx_regras_consolidacao_geral
    ON public.regras_consolidacao_canal(canal_venda_id)
    WHERE modalidade IS NULL;

-- ============================================================================
-- 3. COMENTÁRIOS NA TABELA
-- ============================================================================

COMMENT ON TABLE public.regras_consolidacao_canal IS
    'Configuração de critérios de consolidação de pedidos em demandas de produção.
     Permite ajustar janela de agrupamento, critérios (produto, miolo, data) e
     comportamento quando demanda já existe, sem necessidade de deploy.';

COMMENT ON COLUMN public.regras_consolidacao_canal.canal_venda_id IS
    'Canal de venda ao qual esta regra se aplica';

COMMENT ON COLUMN public.regras_consolidacao_canal.modalidade IS
    'Modalidade logística (STANDARD, EXPRESS, FULFILLMENT, RETIRADA).
     NULL = regra se aplica a todas as modalidades do canal.';

COMMENT ON COLUMN public.regras_consolidacao_canal.janela_agrupamento_horas IS
    'Pedidos dentro de X horas são considerados para agrupamento na mesma demanda';

COMMENT ON COLUMN public.regras_consolidacao_canal.agrupar_por_produto IS
    'Se true, só agrupa pedidos com mesmo produto (ou equivalente)';

COMMENT ON COLUMN public.regras_consolidacao_canal.agrupar_por_miolo IS
    'Se true, só agrupa pedidos com mesmo miolo (componente principal)';

COMMENT ON COLUMN public.regras_consolidacao_canal.agrupar_por_data_entrega IS
    'Se true, só agrupa pedidos com mesma data de entrega (ou janela de 24h)';

COMMENT ON COLUMN public.regras_consolidacao_canal.comportamento_demanda_existente IS
    'ADICIONAR: adiciona pedidos à demanda existente | CRIAR_NOVA: sempre cria nova demanda';

COMMENT ON COLUMN public.regras_consolidacao_canal.politica_consolidacao IS
    'POR_EVENTO: consolida imediatamente ao receber pedido | POR_JANELA: consolida em lotes periódicos';

COMMENT ON COLUMN public.regras_consolidacao_canal.intervalo_consideracao_minutos IS
    'Para política POR_JANELA: intervalo em minutos para considerar pedidos no lote';

-- ============================================================================
-- 4. ROW LEVEL SECURITY (RLS)
-- ============================================================================

ALTER TABLE public.regras_consolidacao_canal ENABLE ROW LEVEL SECURITY;

-- Policy para leitura
DROP POLICY IF EXISTS "Usuários autenticados podem ver regras_consolidacao_canal"
    ON public.regras_consolidacao_canal;
CREATE POLICY "Usuários autenticados podem ver regras_consolidacao_canal"
    ON public.regras_consolidacao_canal
    FOR SELECT
    TO authenticated
    USING (true);

-- Policy para inserção
DROP POLICY IF EXISTS "Usuários autenticados podem criar regras_consolidacao_canal"
    ON public.regras_consolidacao_canal;
CREATE POLICY "Usuários autenticados podem criar regras_consolidacao_canal"
    ON public.regras_consolidacao_canal
    FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Policy para atualização
DROP POLICY IF EXISTS "Usuários autenticados podem atualizar regras_consolidacao_canal"
    ON public.regras_consolidacao_canal;
CREATE POLICY "Usuários autenticados podem atualizar regras_consolidacao_canal"
    ON public.regras_consolidacao_canal
    FOR UPDATE
    TO authenticated
    USING (true);

-- Policy para exclusão
DROP POLICY IF EXISTS "Usuários autenticados podem deletar regras_consolidacao_canal"
    ON public.regras_consolidacao_canal;
CREATE POLICY "Usuários autenticados podem deletar regras_consolidacao_canal"
    ON public.regras_consolidacao_canal
    FOR DELETE
    TO authenticated
    USING (true);

-- ============================================================================
-- 5. FUNÇÃO UTILITÁRIA: Buscar regras de consolidação por canal
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_regras_consolidacao_canal(
    p_canal_venda_id BIGINT,
    p_modalidade VARCHAR(50) DEFAULT NULL
)
RETURNS TABLE (
    canal_venda_id BIGINT,
    modalidade VARCHAR(50),
    janela_agrupamento_horas INTEGER,
    agrupar_por_produto BOOLEAN,
    agrupar_por_miolo BOOLEAN,
    agrupar_por_data_entrega BOOLEAN,
    comportamento_demanda_existente VARCHAR(20),
    politica_consolidacao VARCHAR(20),
    intervalo_consideracao_minutos INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        rc.canal_venda_id,
        rc.modalidade,
        rc.janela_agrupamento_horas,
        rc.agrupar_por_produto,
        rc.agrupar_por_miolo,
        rc.agrupar_por_data_entrega,
        rc.comportamento_demanda_existente,
        rc.politica_consolidacao,
        rc.intervalo_consideracao_minutos
    FROM public.regras_consolidacao_canal rc
    WHERE rc.canal_venda_id = p_canal_venda_id
      AND (rc.modalidade IS NULL OR rc.modalidade = p_modalidade)
    ORDER BY 
        -- Prioriza regra específica da modalidade sobre regra geral
        CASE WHEN rc.modalidade = p_modalidade THEN 0 ELSE 1 END,
        rc.created_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.get_regras_consolidacao_canal IS
    'Busca regras de consolidação para um canal.
     Se modalidade fornecida, prioriza regra específica sobre regra geral (modalidade NULL).
     Retorna no máximo 1 registro.';

-- ============================================================================
-- 6. TRIGGER PARA updated_at
-- ============================================================================

CREATE OR REPLACE TRIGGER update_regras_consolidacao_canal_updated_at
    BEFORE UPDATE ON public.regras_consolidacao_canal
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================================
-- 7. DADOS DE EXEMPLO (comentados - descomentar para popular)
-- ============================================================================

-- Exemplo para canal Shopee (ID hipotético = 1)
-- INSERT INTO public.regras_consolidacao_canal (canal_venda_id, modalidade, janela_agrupamento_horas, comportamento_demanda_existente, politica_consolidacao)
-- VALUES
--     -- Regra geral para todos os pedidos Shopee
--     (1, NULL, 4, 'ADICIONAR', 'POR_EVENTO'),
--     -- Regra específica para Shopee Flex (mais agressiva)
--     (1, 'EXPRESS', 2, 'CRIAR_NOVA', 'POR_EVENTO');

-- Exemplo para canal Mercado Livre (ID hipotético = 2)
-- INSERT INTO public.regras_consolidacao_canal (canal_venda_id, modalidade, janela_agrupamento_horas, agrupar_por_miolo, comportamento_demanda_existente)
-- VALUES
--     (2, NULL, 6, true, 'ADICIONAR');
