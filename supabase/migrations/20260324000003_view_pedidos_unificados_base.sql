-- Migration: View unificada view_pedidos_unificados_base
-- Created: 2026-03-24
--
-- Objetivo: Criar uma view centralizada que calcula has_demanda e fornece
-- detalhes das demandas associadas usando a nova tabela pivot demandas_pedidos.
-- Esta view serve como fonte única de verdade para todas as consultas de pedidos.

-- ============================================================================
-- 1. REMOVER VIEW EXISTENTE (se houver)
-- ============================================================================

DROP VIEW IF EXISTS public.view_pedidos_unificados_base CASCADE;

-- ============================================================================
-- 2. CRIAR VIEW UNIFICADA
-- ============================================================================

CREATE VIEW public.view_pedidos_unificados_base AS
SELECT
    p.id AS pedido_id,
    p.uuid_pedido,
    p.numero_pedido,
    p.codigo_pedido_externo,
    p.origem,
    p.cliente_nome,
    p.cliente_telefone,
    p.cliente_email,
    p.is_flex,
    p.data_limite_envio,
    p.data_pedido,
    p.total_pedido,
    p.situacao_pedido_id,
    s.nome AS situacao_nome,
    p.canal_venda_id,
    cv.nome AS plataforma_nome,
    cv.id AS canal_venda_id_int,
    p.servico_logistico,
    p.modalidade_frete,
    p.endereco_entrega,
    p.numero_entrega,
    p.complemento_entrega,
    p.bairro_entrega,
    p.cidade_entrega,
    p.estado_entrega,
    p.cep_entrega,
    p.created_at,
    p.updated_at,
    
    -- has_demanda: TRUE se existe demanda NÃO CANCELADA associada ao pedido
    (
        EXISTS (
            SELECT 1 
            FROM public.demandas_pedidos dp_rel
            JOIN public.demandas_producao dp ON dp_rel.demanda_id = dp.id
            WHERE dp_rel.pedido_id = p.id 
              AND dp.status != 'CANCELADO'
        )
    ) AS has_demanda,
    
    -- demandas: Array JSON com detalhes das demandas associadas
    (
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
                    'modalidade_logistica', dp.modalidade_logistica,
                    'classificacao_cliente', dp.classificacao_cliente
                ) ORDER BY dp.created_at DESC
            ),
            '[]'::jsonb
        )
        FROM public.demandas_pedidos dp_rel
        JOIN public.demandas_producao dp ON dp_rel.demanda_id = dp.id
        WHERE dp_rel.pedido_id = p.id
          AND dp.status != 'CANCELADO'
    ) AS demandas,
    
    -- itens: Array JSON com itens do pedido
    (
        SELECT COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'item_id', i.id,
                    'sku_externo', i.sku_externo,
                    'sku_interno', i.sku_interno,
                    'descricao', i.descricao,
                    'quantidade', i.quantidade,
                    'valor_unitario', i.valor_unitario,
                    'valor_total', i.valor_total
                ) ORDER BY i.id
            ),
            '[]'::jsonb
        )
        FROM public.itens_pedido i
        WHERE i.pedido_id = p.id
    ) AS itens

FROM public.pedidos p
LEFT JOIN public.situacoes_pedido s ON p.situacao_pedido_id = s.id
LEFT JOIN public.canais_venda cv ON p.canal_venda_id = cv.id;

-- ============================================================================
-- 3. COMENTÁRIOS NA VIEW
-- ============================================================================

COMMENT ON VIEW public.view_pedidos_unificados_base IS 
    'View unificada que fornece dados completos de pedidos com informações de demandas associadas.
     Usa a tabela pivot demandas_pedidos para relacionamento N:N.
     Campo has_demanda considera apenas demandas NÃO CANCELADAS.';

COMMENT ON COLUMN public.view_pedidos_unificados_base.has_demanda IS 
    'TRUE se o pedido possui pelo menos uma demanda de produção associada com status diferente de CANCELADO';

COMMENT ON COLUMN public.view_pedidos_unificados_base.demandas IS 
    'Array JSONB com detalhes de todas as demandas associadas ao pedido (exclui canceladas)';

-- ============================================================================
-- 4. FUNÇÃO DE BUSCA COM FILTROS (opcional, para conveniência)
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_pedidos_unificados_com_filtros(
    p_situacao_ids INTEGER[] DEFAULT NULL,
    p_canal_venda_id INTEGER DEFAULT NULL,
    p_is_flex BOOLEAN DEFAULT NULL,
    p_has_demanda BOOLEAN DEFAULT NULL,
    p_data_inicio TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    p_data_fim TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    p_search TEXT DEFAULT NULL,
    p_limit INTEGER DEFAULT 100,
    p_offset INTEGER DEFAULT 0
)
RETURNS SETOF public.view_pedidos_unificados_base AS $$
BEGIN
    RETURN QUERY
    SELECT v.*
    FROM public.view_pedidos_unificados_base v
    WHERE
        (p_situacao_ids IS NULL OR v.situacao_pedido_id = ANY(p_situacao_ids)) AND
        (p_canal_venda_id IS NULL OR v.canal_venda_id_int = p_canal_venda_id) AND
        (p_is_flex IS NULL OR v.is_flex = p_is_flex) AND
        (p_has_demanda IS NULL OR v.has_demanda = p_has_demanda) AND
        (p_data_inicio IS NULL OR v.data_limite_envio >= p_data_inicio) AND
        (p_data_fim IS NULL OR v.data_limite_envio <= p_data_fim) AND
        (p_search IS NULL OR 
            v.cliente_nome ILIKE '%' || p_search || '%' OR
            v.numero_pedido ILIKE '%' || p_search || '%' OR
            v.codigo_pedido_externo ILIKE '%' || p_search || '%' OR
            v.cliente_email ILIKE '%' || p_search || '%'
        )
    ORDER BY v.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.get_pedidos_unificados_com_filtros IS 
    'Função para buscar pedidos com filtros avançados usando a view unificada';
