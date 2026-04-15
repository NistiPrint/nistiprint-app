-- Migration: Adicionar filtro e retorno de personalizado na list_pedidos_filtrados
-- Data: 2026-04-11
--
-- Objetivo: Permitir filtrar pedidos por personalizado=true/false
--           e retornar a coluna 'personalizado' na resposta

-- Remover versão antiga
DROP FUNCTION IF EXISTS public.list_pedidos_filtrados(
    INTEGER, INTEGER, BOOLEAN, BOOLEAN, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER
);

-- Criar função com parâmetro is_personalizado e coluna de retorno
CREATE OR REPLACE FUNCTION public.list_pedidos_filtrados(
    p_situacao_pedido_id INTEGER DEFAULT NULL,
    p_canal_venda_id INTEGER DEFAULT NULL,
    p_has_demanda BOOLEAN DEFAULT NULL,
    p_is_flex BOOLEAN DEFAULT NULL,
    p_is_personalizado BOOLEAN DEFAULT NULL,
    p_delivery_start_date TEXT DEFAULT NULL,
    p_delivery_end_date TEXT DEFAULT NULL,
    p_search_term TEXT DEFAULT NULL,
    p_sort TEXT DEFAULT 'numero_pedido',
    p_order TEXT DEFAULT 'desc',
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
    situacao_nome VARCHAR,
    situacao_cor VARCHAR,
    is_flex BOOLEAN,
    is_personalizado BOOLEAN,
    demanda_id BIGINT,
    demanda_numero VARCHAR,
    demanda_status VARCHAR,
    total_demandas BIGINT,
    data_limite_envio TIMESTAMPTZ,
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
        sp.nome AS situacao_nome,
        sp.cor_status AS situacao_cor,
        p.is_flex,
        p.personalizado AS is_personalizado,
        v.demanda_id::BIGINT,
        v.demanda_status,
        v.demanda_numero,
        v.total_demandas::BIGINT,
        p.data_limite_envio,
        p.total_pedido,
        EXISTS (
            SELECT 1 FROM demandas_pedidos dp
            WHERE dp.pedido_id = p.id
        ) AS tem_demanda,
        p.origem,
        p.created_at::TIMESTAMPTZ AS created_at
    FROM pedidos p
    LEFT JOIN canais_venda cv ON p.canal_venda_id = cv.id
    LEFT JOIN situacoes_pedido sp ON p.situacao_pedido_id = sp.id
    LEFT JOIN v_pedido_demanda_rastreamento v ON v.pedido_id = p.id
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
        AND (p_is_flex IS NULL OR p.is_flex = p_is_flex)
        AND (p_is_personalizado IS NULL OR p.personalizado = p_is_personalizado)
        AND (p_delivery_start_date IS NULL OR p.data_limite_envio >= p_delivery_start_date::TIMESTAMPTZ)
        AND (p_delivery_end_date IS NULL OR p.data_limite_envio <= p_delivery_end_date::TIMESTAMPTZ)
        AND (p_search_term IS NULL OR p_search_term = '' OR
            p.numero_pedido ILIKE '%' || p_search_term || '%' OR
            p.cliente_nome ILIKE '%' || p_search_term || '%' OR
            p.codigo_pedido_externo ILIKE '%' || p_search_term || '%' OR
            p.cliente_documento ILIKE '%' || p_search_term || '%'
        )
    ORDER BY
        -- Ordenação principal por numero_pedido (como número)
        CASE
            WHEN p_order = 'desc' THEN
                regexp_replace(p.numero_pedido, '[^0-9]', '', 'g')::BIGINT
            ELSE 0
        END DESC,
        CASE
            WHEN p_order = 'asc' THEN
                regexp_replace(p.numero_pedido, '[^0-9]', '', 'g')::BIGINT
            ELSE 0
        END ASC,
        -- Ordenação secundária
        p.data_limite_envio ASC NULLS LAST,
        p.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

-- Grants
GRANT EXECUTE ON FUNCTION public.list_pedidos_filtrados TO authenticated;
GRANT EXECUTE ON FUNCTION public.list_pedidos_filtrados TO anon;

COMMENT ON FUNCTION public.list_pedidos_filtrados IS
'Retorna lista de pedidos com filtros avançados (incluindo personalizado), ordenada por numero_pedido.';
