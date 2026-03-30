-- Migration: Corrige função list_pedidos_filtrados para retornar dados completos do status
-- Data: 2026-03-28
-- 
-- Problema: A função estava retornando apenas situacao_pedido_id, sem o nome e cor do status
-- Solução: Adicionar colunas situacao_nome e situacao_cor ao retorno
--          Adicionar filtro por is_flex (pedidos de entrega rápida)

-- Remover função existente
DROP FUNCTION IF EXISTS public.list_pedidos_filtrados(
    INTEGER, INTEGER, BOOLEAN, TEXT, TEXT, TEXT, INTEGER, INTEGER
);

-- Criar função com dados completos do status e filtro is_flex
CREATE OR REPLACE FUNCTION public.list_pedidos_filtrados(
    p_situacao_pedido_id INTEGER DEFAULT NULL,
    p_canal_venda_id INTEGER DEFAULT NULL,
    p_has_demanda BOOLEAN DEFAULT NULL,
    p_is_flex BOOLEAN DEFAULT NULL,              -- NOVO: Filtro por pedidos Flex
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
    situacao_nome VARCHAR,        -- NOVO: Nome do status
    situacao_cor VARCHAR,         -- NOVO: Cor do status
    is_flex BOOLEAN,              -- NOVO: Indica se é pedido Flex
    data_limite_envio TIMESTAMPTZ,-- NOVO: Data prevista para envio
    total_pedido NUMERIC,
    tem_demanda BOOLEAN,
    origem VARCHAR,
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id::BIGINT AS id,
        p.numero_pedido,
        p.codigo_pedido_externo,
        p.data_venda::TIMESTAMPTZ AS data_venda,
        p.cliente_nome,
        p.cliente_documento,
        p.canal_venda_id,
        cv.nome AS canal_venda_nome,
        p.situacao_pedido_id,
        sp.nome AS situacao_nome,      -- NOVO: Join com situacoes_pedido
        sp.cor_status AS situacao_cor, -- NOVO: Cor do status
        p.is_flex,                     -- NOVO: Pedido Flex
        p.data_limite_envio,           -- NOVO: Data limite para envio
        p.total_pedido,
        EXISTS (
            SELECT 1 FROM demandas_pedidos dp
            WHERE dp.pedido_id = p.id
        ) AS tem_demanda,
        p.origem,
        p.created_at::TIMESTAMPTZ AS created_at
    FROM pedidos p
    LEFT JOIN canais_venda cv ON p.canal_venda_id = cv.id
    LEFT JOIN situacoes_pedido sp ON p.situacao_pedido_id = sp.id  -- NOVO: Join para obter dados do status
    WHERE
        (p_situacao_pedido_id IS NULL OR p.situacao_pedido_id = p_situacao_pedido_id)
        AND (p_canal_venda_id IS NULL OR p.canal_venda_id = p_canal_venda_id)
        AND (
            p_has_demanda IS NULL OR
            (p_has_demanda = TRUE AND EXISTS (
                SELECT 1 FROM demandas_pedidos dp WHERE dp.pedido_id = p.id
            )) OR
            (p_has_demanda = FALSE AND NOT EXISTS (
                SELECT 1 FROM demandas_pedidos dp WHERE dp.pedido_id = p.id
            ))
        )
        AND (p_is_flex IS NULL OR p.is_flex = p_is_flex)  -- NOVO: Filtro por Flex
        AND (p_delivery_start_date IS NULL OR p.data_limite_envio >= p_delivery_start_date::TIMESTAMPTZ)
        AND (p_delivery_end_date IS NULL OR p.data_limite_envio <= p_delivery_end_date::TIMESTAMPTZ)
        AND (p_search_term IS NULL OR p_search_term = '' OR
            p.numero_pedido ILIKE '%' || p_search_term || '%' OR
            p.cliente_nome ILIKE '%' || p_search_term || '%' OR
            p.codigo_pedido_externo ILIKE '%' || p_search_term || '%' OR
            p.cliente_documento ILIKE '%' || p_search_term || '%'
        )
    ORDER BY 
        -- Pedidos Flex aparecem primeiro
        p.is_flex DESC,
        p.data_limite_envio ASC NULLS LAST,
        p.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

-- Grants
GRANT EXECUTE ON FUNCTION public.list_pedidos_filtrados TO authenticated;
GRANT EXECUTE ON FUNCTION public.list_pedidos_filtrados TO anon;

-- Comentário na função
COMMENT ON FUNCTION public.list_pedidos_filtrados IS 
'Retorna lista de pedidos com filtros avançados, incluindo dados completos do status (nome e cor), filtro Flex e data limite de envio.';

-- Testar
-- SELECT * FROM list_pedidos_filtrados(p_is_flex => true, p_limit => 10);
-- SELECT * FROM list_pedidos_filtrados(p_delivery_start_date => '2026-03-28', p_delivery_end_date => '2026-03-30');
