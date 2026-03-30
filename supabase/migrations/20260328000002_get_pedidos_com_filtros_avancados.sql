-- =====================================================
-- FUNÇÃO: get_pedidos_com_filtros_avancados
-- =====================================================
-- Lista pedidos com filtros avançados para a nova tela de gestão
-- =====================================================

-- Remover função existente se houver (para evitar conflito)
DROP FUNCTION IF EXISTS public.get_pedidos_com_filtros_avancados(
    INTEGER, INTEGER, BOOLEAN, TEXT, TEXT, TEXT, INTEGER, INTEGER
);

-- Criar nova função
CREATE OR REPLACE FUNCTION public.get_pedidos_com_filtros_avancados(
    p_situacao_pedido_id INTEGER DEFAULT NULL,
    p_canal_venda_id INTEGER DEFAULT NULL,
    p_has_demanda BOOLEAN DEFAULT NULL,
    p_delivery_start_date TEXT DEFAULT NULL,
    p_delivery_end_date TEXT DEFAULT NULL,
    p_search_term TEXT DEFAULT NULL,
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    id BIGINT,
    numero_pedido VARCHAR,
    codigo_pedido_externo VARCHAR,
    data_venda TIMESTAMPTZ,
    cliente_nome VARCHAR,
    cliente_documento VARCHAR,
    canal_venda_id INTEGER,
    canal_venda_nome VARCHAR,
    situacao_pedido_id INTEGER,
    total_pedido NUMERIC,
    tem_demanda BOOLEAN,
    origem VARCHAR,
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        p.id,
        p.numero_pedido,
        p.codigo_pedido_externo,
        p.data_venda,
        p.cliente_nome,
        p.cliente_documento,
        p.canal_venda_id,
        cv.nome AS canal_venda_nome,
        p.situacao_pedido_id,
        p.total_pedido,
        -- Verifica se tem demanda vinculada (usando tabela pivot demandas_pedidos)
        EXISTS (
            SELECT 1 FROM demandas_pedidos dp 
            WHERE dp.pedido_id = p.id
        ) AS tem_demanda,
        p.origem,
        p.created_at
    FROM pedidos p
    LEFT JOIN canais_venda cv ON p.canal_venda_id = cv.id
    WHERE 
        -- Filtro por status
        (p_situacao_pedido_id IS NULL OR p.situacao_pedido_id = p_situacao_pedido_id)
        
        -- Filtro por canal
        AND (p_canal_venda_id IS NULL OR p.canal_venda_id = p_canal_venda_id)
        
        -- Filtro por ter/não ter demanda
        AND (
            p_has_demanda IS NULL OR
            (p_has_demanda = TRUE AND EXISTS (
                SELECT 1 FROM demandas_pedidos dp WHERE dp.pedido_id = p.id
            )) OR
            (p_has_demanda = FALSE AND NOT EXISTS (
                SELECT 1 FROM demandas_pedidos dp WHERE dp.pedido_id = p.id
            ))
        )
        
        -- Filtro por período de entrega
        AND (p_delivery_start_date IS NULL OR p.data_venda >= p_delivery_start_date::TIMESTAMPTZ)
        AND (p_delivery_end_date IS NULL OR p.data_venda <= p_delivery_end_date::TIMESTAMPTZ)
        
        -- Filtro por busca (numero, cliente, código externo)
        AND (p_search_term IS NULL OR p_search_term = '' OR 
            p.numero_pedido ILIKE '%' || p_search_term || '%' OR
            p.cliente_nome ILIKE '%' || p_search_term || '%' OR
            p.codigo_pedido_externo ILIKE '%' || p_search_term || '%' OR
            p.cliente_documento ILIKE '%' || p_search_term || '%'
        )
        
    ORDER BY p.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

-- Comentários
COMMENT ON FUNCTION public.get_pedidos_com_filtros_avancados IS 
'Lista pedidos com filtros avançados para gestão unificada. Suporta filtros por status, canal, demanda, período e busca textual.';

-- Grants
GRANT EXECUTE ON FUNCTION public.get_pedidos_com_filtros_avancados TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_pedidos_com_filtros_avancados TO anon;
