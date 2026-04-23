-- Migration: Canal Modalidade Mapeamento
-- Created: 2026-04-02
--
-- Objetivo: Criar tabela de mapeamento configurável para derivar modalidade logística
-- a partir do servico_logistico recebido de webhooks (Bling, Shopee, etc.)
--
-- Problema resolvido: Quando o Bling envia "Entrega Rápida Shopee", o sistema precisa
-- mapear isso para EXPRESS. Sem essa tabela, a derivação é hardcoded.

-- ============================================================================
-- 1. CRIAR TABELA canal_modalidade_mapeamento
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.canal_modalidade_mapeamento (
    id BIGSERIAL PRIMARY KEY,
    canal_venda_id BIGINT NOT NULL REFERENCES public.canais_venda(id) ON DELETE CASCADE,
    
    -- Padrões de string que chegam do servico_logistico
    -- Suporta múltiplos valores via array (ex: ['%flex%', '%rápida%', 'Entrega Expressa'])
    padroes_servico TEXT[] NOT NULL,
    
    -- Modalidade logística interna (STANDARD, EXPRESS, FULFILLMENT, RETIRADA)
    modalidade VARCHAR(50) NOT NULL,
    
    -- Prioridade do padrão (maior = mais específico, tem precedência)
    prioridade INTEGER DEFAULT 0,
    
    -- Descrição opcional para documentação interna
    descricao TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Garante que não haja duplicatas exatas
    CONSTRAINT uq_canal_modalidade_padroes UNIQUE (canal_venda_id, padroes_servico, modalidade)
);

-- ============================================================================
-- 2. ÍNDICES PARA PERFORMANCE
-- ============================================================================

-- Índice para busca por canal
CREATE INDEX IF NOT EXISTS idx_canal_modalidade_canal_id
    ON public.canal_modalidade_mapeamento(canal_venda_id)
    WHERE modalidade IN ('STANDARD', 'EXPRESS', 'FULFILLMENT', 'RETIRADA');

-- Índice para busca por canal + modalidade
CREATE INDEX IF NOT EXISTS idx_canal_modalidade_canal_modalidade
    ON public.canal_modalidade_mapeamento(canal_venda_id, modalidade);

-- ============================================================================
-- 3. COMENTÁRIOS NA TABELA
-- ============================================================================

COMMENT ON TABLE public.canal_modalidade_mapeamento IS
    'Mapeamento configurável de padrões de servico_logistico para modalidade logística interna.
     Permite que o sistema derive automaticamente STANDARD, EXPRESS, FULFILLMENT ou RETIRADA
     a partir de strings como "Entrega Rápida Shopee", "Flex", "Normal", etc.';

COMMENT ON COLUMN public.canal_modalidade_mapeamento.canal_venda_id IS
    'Canal de venda ao qual este mapeamento se aplica';

COMMENT ON COLUMN public.canal_modalidade_mapeamento.padroes_servico IS
    'Array de padrões LIKE para matching (ex: [''%flex%'', ''%rápida%'', ''Entrega Expressa''])';

COMMENT ON COLUMN public.canal_modalidade_mapeamento.modalidade IS
    'Modalidade logística interna: STANDARD, EXPRESS, FULFILLMENT, RETIRADA';

COMMENT ON COLUMN public.canal_modalidade_mapeamento.prioridade IS
    'Prioridade do padrão. Maior = mais específico. Usado para desempate quando múltiplos padrões casam.';

-- ============================================================================
-- 4. ROW LEVEL SECURITY (RLS)
-- ============================================================================

ALTER TABLE public.canal_modalidade_mapeamento ENABLE ROW LEVEL SECURITY;

-- Policy para leitura
DROP POLICY IF EXISTS "Usuários autenticados podem ver canal_modalidade_mapeamento"
    ON public.canal_modalidade_mapeamento;
CREATE POLICY "Usuários autenticados podem ver canal_modalidade_mapeamento"
    ON public.canal_modalidade_mapeamento
    FOR SELECT
    TO authenticated
    USING (true);

-- Policy para inserção
DROP POLICY IF EXISTS "Usuários autenticados podem criar canal_modalidade_mapeamento"
    ON public.canal_modalidade_mapeamento;
CREATE POLICY "Usuários autenticados podem criar canal_modalidade_mapeamento"
    ON public.canal_modalidade_mapeamento
    FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Policy para atualização
DROP POLICY IF EXISTS "Usuários autenticados podem atualizar canal_modalidade_mapeamento"
    ON public.canal_modalidade_mapeamento;
CREATE POLICY "Usuários autenticados podem atualizar canal_modalidade_mapeamento"
    ON public.canal_modalidade_mapeamento
    FOR UPDATE
    TO authenticated
    USING (true);

-- Policy para exclusão
DROP POLICY IF EXISTS "Usuários autenticados podem deletar canal_modalidade_mapeamento"
    ON public.canal_modalidade_mapeamento;
CREATE POLICY "Usuários autenticados podem deletar canal_modalidade_mapeamento"
    ON public.canal_modalidade_mapeamento
    FOR DELETE
    TO authenticated
    USING (true);

-- ============================================================================
-- 5. FUNÇÃO UTILITÁRIA: Buscar modalidade por servico_logistico
-- ============================================================================

CREATE OR REPLACE FUNCTION public.derivar_modalidade_logistica(
    p_canal_venda_id BIGINT,
    p_servico_logistico TEXT
)
RETURNS VARCHAR(50) AS $$
DECLARE
    v_modalidade VARCHAR(50);
    v_padraes TEXT[];
    v_padrao TEXT;
BEGIN
    -- Iterar sobre mapeamentos do canal, ordenados por prioridade (maior primeiro)
    FOR v_modalidade, v_padroes IN
        SELECT cmm.modalidade, cmm.padroes_servico
        FROM public.canal_modalidade_mapeamento cmm
        WHERE cmm.canal_venda_id = p_canal_venda_id
        ORDER BY cmm.prioridade DESC, cmm.created_at DESC
    LOOP
        -- Verificar cada padrão do array
        FOREACH v_padrao IN ARRAY v_padroes
        LOOP
            IF p_servico_logistico ILIKE v_padrao THEN
                RETURN v_modalidade;
            END IF;
        END LOOP;
    END LOOP;
    
    -- Fallback: retornar NULL se nenhum padrão casar
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.derivar_modalidade_logistica IS
    'Deriva modalidade logística (STANDARD, EXPRESS, FULFILLMENT, RETIRADA)
     a partir do servico_logistico recebido, usando mapeamentos configurados por canal.
     Retorna NULL se nenhum padrão casar.';

-- ============================================================================
-- 6. FUNÇÃO UTILITÁRIA: Listar todos os mapeamentos de um canal (JSON)
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_mapeamentos_modalidade_canal(
    p_canal_venda_id BIGINT
)
RETURNS JSONB AS $$
BEGIN
    RETURN (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'id', cmm.id,
                    'padroes_servico', cmm.padroes_servico,
                    'modalidade', cmm.modalidade,
                    'prioridade', cmm.prioridade,
                    'descricao', cmm.descricao,
                    'created_at', cmm.created_at
                ) ORDER BY cmm.prioridade DESC
            ),
            '[]'::jsonb
        )
        FROM public.canal_modalidade_mapeamento cmm
        WHERE cmm.canal_venda_id = p_canal_venda_id
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.get_mapeamentos_modalidade_canal IS
    'Retorna array JSON com todos os mapeamentos de modalidade de um canal';

-- ============================================================================
-- 7. TRIGGER PARA updated_at
-- ============================================================================

CREATE OR REPLACE TRIGGER update_canal_modalidade_mapeamento_updated_at
    BEFORE UPDATE ON public.canal_modalidade_mapeamento
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================================
-- 8. DADOS DE EXEMPLO (comentados - descomentar para popular)
-- ============================================================================

-- Exemplo para canal Shopee (ID hipotético = 1)
-- INSERT INTO public.canal_modalidade_mapeamento (canal_venda_id, padroes_servico, modalidade, prioridade, descricao)
-- VALUES
--     (1, ARRAY['%flex%', '%rápida%', 'Entrega Rápida'], 'EXPRESS', 100, 'Shopee Flex/Entrega Rápida'),
--     (1, ARRAY['%normal%', '%padrão%', 'Entrega Padrão'], 'STANDARD', 50, 'Shopee Normal'),
--     (1, ARRAY['%full%', '%fulfillment%'], 'FULFILLMENT', 100, 'Shopee Fulfillment');

-- Exemplo para canal Mercado Livre (ID hipotético = 2)
-- INSERT INTO public.canal_modalidade_mapeamento (canal_venda_id, padroes_servico, modalidade, prioridade, descricao)
-- VALUES
--     (2, ARRAY['%flex%', '%rápida%', 'Mercado Envio Flex'], 'EXPRESS', 100, 'ML Flex'),
--     (2, ARRAY['%normal%', '%padrão%', 'Mercado Envio Clássico'], 'STANDARD', 50, 'ML Normal');
