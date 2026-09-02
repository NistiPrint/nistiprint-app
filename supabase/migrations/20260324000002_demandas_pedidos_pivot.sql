-- Migration: Tabela pivot demandas_pedidos para relacionamento N:N
-- Created: 2026-03-24
-- 
-- Objetivo: Substituir o rastreamento complexo por item (demandas_item_origem)
-- por um relacionamento direto e simples entre Demandas e Pedidos.
--
-- Regra de Negócio: Demanda 1 : N Pedidos (e N:N no geral)
-- Usuários podem saber facilmente se um pedido tem demanda e quais demandas.

-- ============================================================================
-- 1. CRIAR TABELA PIVOT demandas_pedidos
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.demandas_pedidos (
    id BIGSERIAL PRIMARY KEY,
    demanda_id BIGINT NOT NULL,
    pedido_id BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT fk_demandas_pedidos_demanda FOREIGN KEY (demanda_id) 
        REFERENCES public.demandas_producao(id) ON DELETE CASCADE,
    CONSTRAINT fk_demandas_pedidos_pedido FOREIGN KEY (pedido_id) 
        REFERENCES public.pedidos(id) ON DELETE CASCADE,
    -- Garante que não haja duplicatas (mesma demanda + mesmo pedido)
    CONSTRAINT uq_demandas_pedidos_demanda_pedido UNIQUE (demanda_id, pedido_id)
);

-- ============================================================================
-- 2. ÍNDICES PARA PERFORMANCE
-- ============================================================================

-- Índice para buscar demandas de um pedido (has_demanda, lista de demandas)
CREATE INDEX IF NOT EXISTS idx_demandas_pedidos_pedido_id 
    ON public.demandas_pedidos(pedido_id);

-- Índice para buscar pedidos de uma demanda
CREATE INDEX IF NOT EXISTS idx_demandas_pedidos_demanda_id 
    ON public.demandas_pedidos(demanda_id);

-- Índice composto para consultas que filtram por demanda e pedido
CREATE INDEX IF NOT EXISTS idx_demandas_pedidos_demanda_pedido 
    ON public.demandas_pedidos(demanda_id, pedido_id);

-- ============================================================================
-- 3. COMENTÁRIOS NA TABELA
-- ============================================================================

COMMENT ON TABLE public.demandas_pedidos IS 
    'Tabela pivot para relacionamento N:N entre demandas de produção e pedidos. 
     Substitui o rastreamento complexo por item (demandas_item_origem) por um 
     vínculo direto Demanda : Pedidos.';

COMMENT ON COLUMN public.demandas_pedidos.demanda_id IS 
    'ID da demanda de produção';

COMMENT ON COLUMN public.demandas_pedidos.pedido_id IS 
    'ID do pedido unificado';

COMMENT ON COLUMN public.demandas_pedidos.created_at IS 
    'Data/hora do vínculo entre demanda e pedido';

-- ============================================================================
-- 4. ROW LEVEL SECURITY (RLS)
-- ============================================================================

ALTER TABLE public.demandas_pedidos ENABLE ROW LEVEL SECURITY;

-- Policy para leitura
DROP POLICY IF EXISTS "Usuários autenticados podem ver demandas_pedidos" 
    ON public.demandas_pedidos;
CREATE POLICY "Usuários autenticados podem ver demandas_pedidos"
    ON public.demandas_pedidos
    FOR SELECT
    TO authenticated
    USING (true);

-- Policy para inserção
DROP POLICY IF EXISTS "Usuários autenticados podem criar demandas_pedidos" 
    ON public.demandas_pedidos;
CREATE POLICY "Usuários autenticados podem criar demandas_pedidos"
    ON public.demandas_pedidos
    FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Policy para atualização
DROP POLICY IF EXISTS "Usuários autenticados podem atualizar demandas_pedidos" 
    ON public.demandas_pedidos;
CREATE POLICY "Usuários autenticados podem atualizar demandas_pedidos"
    ON public.demandas_pedidos
    FOR UPDATE
    TO authenticated
    USING (true);

-- Policy para exclusão
DROP POLICY IF EXISTS "Usuários autenticados podem deletar demandas_pedidos" 
    ON public.demandas_pedidos;
CREATE POLICY "Usuários autenticados podem deletar demandas_pedidos"
    ON public.demandas_pedidos
    FOR DELETE
    TO authenticated
    USING (true);

-- ============================================================================
-- 5. FUNÇÃO UTILITÁRIA: Verificar se pedido tem demanda
-- ============================================================================

CREATE OR REPLACE FUNCTION public.pedido_tem_demanda(p_pedido_id BIGINT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 
        FROM public.demandas_pedidos dp_rel
        JOIN public.demandas_producao dp ON dp_rel.demanda_id = dp.id
        WHERE dp_rel.pedido_id = p_pedido_id 
          AND dp.status != 'CANCELADO'
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.pedido_tem_demanda IS 
    'Verifica se um pedido possui demanda de produção associada (não cancelada)';

-- ============================================================================
-- 6. FUNÇÃO UTILITÁRIA: Buscar demandas de um pedido (JSON)
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_demandas_do_pedido(p_pedido_id BIGINT)
RETURNS JSONB AS $$
BEGIN
    RETURN (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'demanda_id', dp.id,
                    'demanda_uuid', dp.demanda_id,
                    'descricao', dp.descricao,
                    'status', dp.status,
                    'tipo_demanda', dp.tipo_demanda,
                    'quantidade', dp.quantidade,
                    'data_entrega', dp.data_entrega,
                    'prioridade', dp.prioridade,
                    'created_at', dp.created_at
                )
            ),
            '[]'::jsonb
        )
        FROM public.demandas_pedidos dp_rel
        JOIN public.demandas_producao dp ON dp_rel.demanda_id = dp.id
        WHERE dp_rel.pedido_id = p_pedido_id
          AND dp.status != 'CANCELADO'
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.get_demandas_do_pedido IS 
    'Retorna array JSON com todas as demandas associadas a um pedido';

-- ============================================================================
-- 7. FUNÇÃO UTILITÁRIA: Buscar pedidos de uma demanda (JSON)
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_pedidos_da_demanda(p_demanda_id BIGINT)
RETURNS JSONB AS $$
BEGIN
    RETURN (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'pedido_id', p.id,
                    'numero_pedido', p.numero_pedido,
                    'codigo_pedido_externo', p.codigo_pedido_externo,
                    'origem', p.origem,
                    'cliente_nome', p.cliente_nome,
                    'data_limite_envio', p.data_limite_envio,
                    'total_pedido', p.total_pedido,
                    'is_flex', p.is_flex
                )
            ),
            '[]'::jsonb
        )
        FROM public.demandas_pedidos dp_rel
        JOIN public.pedidos p ON dp_rel.pedido_id = p.id
        WHERE dp_rel.demanda_id = p_demanda_id
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.get_pedidos_da_demanda IS 
    'Retorna array JSON com todos os pedidos associados a uma demanda';
