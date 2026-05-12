-- Lista e filtra origens de pedido por chave estável:
--   canal:<id>, marketplace:<id>, bling_loja:<loja_id>

DROP FUNCTION IF EXISTS public.get_pedidos_origem_options();

CREATE OR REPLACE FUNCTION public.get_pedidos_origem_options()
RETURNS TABLE (
    key TEXT,
    nome TEXT,
    tipo TEXT,
    id INTEGER,
    loja_id TEXT,
    total BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH canal_options AS (
        SELECT
            ('canal:' || p.canal_venda_id)::TEXT AS key,
            COALESCE(cv.nome, 'Canal ' || p.canal_venda_id)::TEXT AS nome,
            'canal'::TEXT AS tipo,
            p.canal_venda_id::INTEGER AS id,
            NULL::TEXT AS loja_id,
            COUNT(*)::BIGINT AS total
        FROM public.pedidos p
        LEFT JOIN public.canais_venda cv ON cv.id = p.canal_venda_id
        WHERE p.canal_venda_id IS NOT NULL
        GROUP BY p.canal_venda_id, cv.nome
    ),
    marketplace_options AS (
        SELECT
            ('marketplace:' || p.marketplace_integration_id)::TEXT AS key,
            COALESCE(ii.instance_name, im.name, 'Marketplace ' || p.marketplace_integration_id)::TEXT AS nome,
            'marketplace'::TEXT AS tipo,
            p.marketplace_integration_id::INTEGER AS id,
            NULL::TEXT AS loja_id,
            COUNT(*)::BIGINT AS total
        FROM public.pedidos p
        LEFT JOIN public.installed_integrations ii ON ii.id = p.marketplace_integration_id
        LEFT JOIN public.integration_modules im ON im.id = ii.module_id
        WHERE p.marketplace_integration_id IS NOT NULL
        GROUP BY p.marketplace_integration_id, ii.instance_name, im.name
    ),
    bling_order_options AS (
        SELECT
            ('bling_loja:' || pb.loja_id)::TEXT AS key,
            COALESCE(
                MAX(cc.aggregator_store_name),
                MAX(cv.nome) || ' - Loja ' || pb.loja_id,
                'Loja Bling ' || pb.loja_id
            )::TEXT AS nome,
            'bling_loja'::TEXT AS tipo,
            NULL::INTEGER AS id,
            pb.loja_id::TEXT AS loja_id,
            COUNT(DISTINCT p.id)::BIGINT AS total
        FROM public.pedidos p
        JOIN public.pedidos_bling pb ON pb.id = p.pedido_bling_id
        LEFT JOIN public.channel_connections cc
            ON cc.aggregator_store_id = pb.loja_id::TEXT
           AND cc.is_active = true
           AND (
                cc.bling_integration_id IS NULL
                OR p.bling_integration_id IS NULL
                OR cc.bling_integration_id = p.bling_integration_id
           )
        LEFT JOIN public.canais_venda cv ON cv.id = COALESCE(cc.channel_id, p.canal_venda_id)
        WHERE pb.loja_id IS NOT NULL
        GROUP BY pb.loja_id
    ),
    bling_connection_options AS (
        SELECT
            ('bling_loja:' || cc.aggregator_store_id)::TEXT AS key,
            COALESCE(
                cc.aggregator_store_name,
                cv.nome || ' - Loja ' || cc.aggregator_store_id,
                'Loja Bling ' || cc.aggregator_store_id
            )::TEXT AS nome,
            'bling_loja'::TEXT AS tipo,
            NULL::INTEGER AS id,
            cc.aggregator_store_id::TEXT AS loja_id,
            COUNT(DISTINCT CASE
                WHEN pb_any.loja_id::TEXT = cc.aggregator_store_id OR pb_any.id IS NULL
                THEN p.id
            END)::BIGINT AS total
        FROM public.channel_connections cc
        LEFT JOIN public.canais_venda cv ON cv.id = cc.channel_id
        LEFT JOIN public.pedidos p
            ON (
                p.canal_venda_id = cc.channel_id
                OR p.marketplace_integration_id = cc.marketplace_integration_id
                OR (
                    cc.bling_integration_id IS NOT NULL
                    AND p.bling_integration_id = cc.bling_integration_id
                )
            )
        LEFT JOIN public.pedidos_bling pb_any ON pb_any.id = p.pedido_bling_id
        WHERE cc.is_active = true
          AND cc.aggregator_store_id IS NOT NULL
        GROUP BY cc.aggregator_store_id, cc.aggregator_store_name, cv.nome
    )
    SELECT
        grouped.key,
        COALESCE(
            MAX(grouped.nome) FILTER (WHERE grouped.total > 0),
            MAX(grouped.nome)
        ) AS nome,
        MAX(grouped.tipo) AS tipo,
        MAX(grouped.id) AS id,
        MAX(grouped.loja_id) AS loja_id,
        MAX(grouped.total)::BIGINT AS total
    FROM (
        SELECT * FROM canal_options
        UNION ALL
        SELECT * FROM marketplace_options
        UNION ALL
        SELECT * FROM bling_order_options
        UNION ALL
        SELECT * FROM bling_connection_options
    ) grouped
    GROUP BY grouped.key
    ORDER BY
        CASE MAX(grouped.tipo)
            WHEN 'bling_loja' THEN 1
            WHEN 'marketplace' THEN 2
            ELSE 3
        END,
        nome;
END;
$$ LANGUAGE plpgsql STABLE;

GRANT EXECUTE ON FUNCTION public.get_pedidos_origem_options TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_pedidos_origem_options TO anon;

DROP FUNCTION IF EXISTS public.list_pedidos_filtrados(
    INTEGER, INTEGER, BOOLEAN, BOOLEAN, BOOLEAN, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER
);

CREATE OR REPLACE FUNCTION public.list_pedidos_filtrados(
    p_situacao_pedido_id INTEGER DEFAULT NULL,
    p_canal_venda_id INTEGER DEFAULT NULL,
    p_origem_pedido_key TEXT DEFAULT NULL,
    p_has_demanda BOOLEAN DEFAULT NULL,
    p_is_flex BOOLEAN DEFAULT NULL,
    p_is_personalizado BOOLEAN DEFAULT NULL,
    p_delivery_start_date TEXT DEFAULT NULL,
    p_delivery_end_date TEXT DEFAULT NULL,
    p_pedido_date_start TEXT DEFAULT NULL,
    p_pedido_date_end TEXT DEFAULT NULL,
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
    marketplace_integration_id INTEGER,
    marketplace_nome VARCHAR,
    marketplace_slug VARCHAR,
    marketplace_color VARCHAR,
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
DECLARE
    v_origem_tipo TEXT;
    v_origem_valor TEXT;
BEGIN
    v_origem_tipo := NULLIF(split_part(COALESCE(p_origem_pedido_key, ''), ':', 1), '');
    v_origem_valor := NULLIF(split_part(COALESCE(p_origem_pedido_key, ''), ':', 2), '');

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
        p.marketplace_integration_id,
        ii.instance_name AS marketplace_nome,
        im.slug AS marketplace_slug,
        CASE
            WHEN im.slug = 'shopee' THEN '#EE4D2D'
            WHEN im.slug = 'mercadolivre' THEN '#FFF159'
            WHEN im.slug = 'amazon' THEN '#FF9900'
            WHEN im.slug = 'shein' THEN '#FF6B6B'
            ELSE '#007bff'
        END AS marketplace_color,
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
            SELECT 1 FROM public.demandas_pedidos dp
            WHERE dp.pedido_id = p.id
        ) AS tem_demanda,
        p.origem,
        p.created_at::TIMESTAMPTZ AS created_at
    FROM public.pedidos p
    LEFT JOIN public.canais_venda cv ON p.canal_venda_id = cv.id
    LEFT JOIN public.installed_integrations ii ON p.marketplace_integration_id = ii.id
    LEFT JOIN public.integration_modules im ON ii.module_id = im.id
    LEFT JOIN public.situacoes_pedido sp ON p.situacao_pedido_id = sp.id
    LEFT JOIN public.v_pedido_demanda_rastreamento v ON v.pedido_id = p.id
    LEFT JOIN public.pedidos_bling pb ON pb.id = p.pedido_bling_id
    WHERE
        (p_situacao_pedido_id IS NULL OR p.situacao_pedido_id = p_situacao_pedido_id)
        AND (
            p_canal_venda_id IS NULL
            OR p.canal_venda_id = p_canal_venda_id
            OR p.marketplace_integration_id = p_canal_venda_id
        )
        AND (
            p_origem_pedido_key IS NULL
            OR p_origem_pedido_key = ''
            OR (
                v_origem_tipo = 'canal'
                AND v_origem_valor ~ '^[0-9]+$'
                AND p.canal_venda_id = v_origem_valor::INTEGER
            )
            OR (
                v_origem_tipo = 'marketplace'
                AND v_origem_valor ~ '^[0-9]+$'
                AND p.marketplace_integration_id = v_origem_valor::INTEGER
            )
            OR (
                v_origem_tipo = 'bling_loja'
                AND v_origem_valor IS NOT NULL
                AND (
                    pb.loja_id::TEXT = v_origem_valor
                    OR EXISTS (
                        SELECT 1
                        FROM public.channel_connections cc
                        WHERE cc.is_active = true
                          AND cc.aggregator_store_id = v_origem_valor
                          AND pb.id IS NULL
                          AND (
                              cc.channel_id = p.canal_venda_id
                              OR cc.marketplace_integration_id = p.marketplace_integration_id
                              OR (
                                  cc.bling_integration_id IS NOT NULL
                                  AND cc.bling_integration_id = p.bling_integration_id
                              )
                          )
                    )
                )
            )
        )
        AND (
            p_has_demanda IS NULL OR
            (p_has_demanda = TRUE AND EXISTS (
                SELECT 1 FROM public.demandas_pedidos dp WHERE dp.pedido_id = p.id
            )) OR
            (p_has_demanda = FALSE AND NOT EXISTS (
                SELECT 1 FROM public.demandas_pedidos dp WHERE dp.pedido_id = p.id
            ))
        )
        AND (p_is_flex IS NULL OR p.is_flex = p_is_flex)
        AND (p_is_personalizado IS NULL OR p.personalizado = p_is_personalizado)
        AND (p_delivery_start_date IS NULL OR p.data_limite_envio >= p_delivery_start_date::TIMESTAMPTZ)
        AND (p_delivery_end_date IS NULL OR p.data_limite_envio <= p_delivery_end_date::TIMESTAMPTZ)
        AND (p_pedido_date_start IS NULL OR p.data_venda::DATE >= p_pedido_date_start::DATE)
        AND (p_pedido_date_end IS NULL OR p.data_venda::DATE <= p_pedido_date_end::DATE)
        AND (p_search_term IS NULL OR p_search_term = '' OR
            p.numero_pedido ILIKE '%' || p_search_term || '%' OR
            p.cliente_nome ILIKE '%' || p_search_term || '%' OR
            p.codigo_pedido_externo ILIKE '%' || p_search_term || '%' OR
            p.cliente_documento ILIKE '%' || p_search_term || '%'
        )
    ORDER BY
        CASE
            WHEN p_order = 'desc' THEN
                NULLIF(regexp_replace(p.numero_pedido, '[^0-9]', '', 'g'), '')::BIGINT
            ELSE NULL
        END DESC NULLS LAST,
        CASE
            WHEN p_order = 'asc' THEN
                NULLIF(regexp_replace(p.numero_pedido, '[^0-9]', '', 'g'), '')::BIGINT
            ELSE NULL
        END ASC NULLS LAST,
        p.data_limite_envio ASC NULLS LAST,
        p.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION public.list_pedidos_filtrados TO authenticated;
GRANT EXECUTE ON FUNCTION public.list_pedidos_filtrados TO anon;

COMMENT ON FUNCTION public.get_pedidos_origem_options IS
'Retorna origens distintas para filtro de pedidos usando canal, marketplace e loja Bling.';

COMMENT ON FUNCTION public.list_pedidos_filtrados IS
'Retorna lista de pedidos com filtros avançados, incluindo origem_pedido_key.';
