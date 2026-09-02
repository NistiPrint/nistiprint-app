-- Migration: Optimize Order Filters RPC, Fix Security and Performance
-- Date: 2026-05-21
-- Target: public.list_pedidos_filtrados, RLS on rule tables, index cleanup

-- 1. Security: Enable RLS on rule and log tables
ALTER TABLE public.entity_correlation_mapping ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.integration_status_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pedidos_mercadolivre ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fulfillment_classification_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.debug_rpc_logs ENABLE ROW LEVEL SECURITY;

-- Note: Policies should be added by the user depending on their specific access needs.
-- By default, enabling RLS without policies blocks all access (security by default).

-- 2. Performance: Cleanup redundant indexes
DROP INDEX IF EXISTS public.idx_pedidos_bling_integration_id_filter;

-- 3. Enhance list_pedidos_filtrados RPC
-- Drop existing versions to handle signature changes
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (SELECT oid::regprocedure as sig FROM pg_proc WHERE proname = 'list_pedidos_filtrados') LOOP
        EXECUTE 'DROP FUNCTION ' || r.sig;
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.list_pedidos_filtrados(
    p_situacao_pedido_id INTEGER DEFAULT NULL,
    p_canal_venda_id INTEGER DEFAULT NULL,
    p_origem_pedido_key TEXT DEFAULT NULL,
    p_bling_integration_id INTEGER DEFAULT NULL,
    p_has_demanda BOOLEAN DEFAULT NULL,
    p_is_flex BOOLEAN DEFAULT NULL,
    p_is_personalizado BOOLEAN DEFAULT NULL,
    p_is_fulfillment BOOLEAN DEFAULT NULL,
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
    bling_integration_id INTEGER,
    bling_integration_nome VARCHAR,
    bling_loja_id VARCHAR,
    situacao_pedido_id INTEGER,
    situacao_nome VARCHAR,
    situacao_cor VARCHAR,
    is_flex BOOLEAN,
    is_personalizado BOOLEAN,
    is_fulfillment BOOLEAN,
    demanda_id BIGINT,
    demanda_numero VARCHAR,
    demanda_status VARCHAR,
    total_demandas BIGINT,
    data_limite_envio TIMESTAMPTZ,
    total_pedido NUMERIC,
    tem_demanda BOOLEAN,
    origem VARCHAR,
    created_at TIMESTAMPTZ,
    total_count BIGINT
) AS $$
DECLARE
    v_origem_tipo TEXT;
    v_origem_valor TEXT;
BEGIN
    v_origem_tipo := NULLIF(split_part(COALESCE(p_origem_pedido_key, ''), ':', 1), '');
    v_origem_valor := NULLIF(split_part(COALESCE(p_origem_pedido_key, ''), ':', 2), '');

    RETURN QUERY
    WITH filtered_pedidos AS (
        SELECT
            p.id,
            p.numero_pedido,
            p.codigo_pedido_externo,
            p.data_venda,
            p.cliente_nome,
            p.cliente_documento,
            p.canal_venda_id,
            p.marketplace_integration_id,
            p.bling_integration_id,
            p.situacao_pedido_id,
            p.is_flex,
            p.personalizado,
            p.is_fulfillment,
            p.data_limite_envio,
            p.total_pedido,
            p.origem,
            p.created_at,
            p.pedido_bling_id
        FROM public.pedidos p
        LEFT JOIN public.pedidos_bling pb ON pb.id = p.pedido_bling_id
        WHERE
            (p_situacao_pedido_id IS NULL OR p.situacao_pedido_id = p_situacao_pedido_id)
            AND (p_bling_integration_id IS NULL OR p.bling_integration_id = p_bling_integration_id)
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
            AND (p_is_fulfillment IS NULL OR p.is_fulfillment = p_is_fulfillment)
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
    )
    SELECT
        f.id::BIGINT,
        f.numero_pedido::VARCHAR,
        f.codigo_pedido_externo::VARCHAR,
        f.data_venda::TIMESTAMPTZ,
        f.cliente_nome::VARCHAR,
        f.cliente_documento::VARCHAR,
        f.canal_venda_id,
        cv.nome::VARCHAR AS canal_venda_nome,
        f.marketplace_integration_id,
        ii.instance_name::VARCHAR AS marketplace_nome,
        im.slug::VARCHAR AS marketplace_slug,
        (CASE
            WHEN im.slug = 'shopee' THEN '#EE4D2D'
            WHEN im.slug = 'mercadolivre' THEN '#FFF159'
            WHEN im.slug = 'amazon' THEN '#FF9900'
            WHEN im.slug = 'shein' THEN '#FF6B6B'
            ELSE '#007bff'
        END)::VARCHAR AS marketplace_color,
        f.bling_integration_id,
        bi.instance_name::VARCHAR AS bling_integration_nome,
        pb.loja_id::VARCHAR AS bling_loja_id,
        f.situacao_pedido_id,
        sp.nome::VARCHAR AS situacao_nome,
        sp.cor_status::VARCHAR AS situacao_cor,
        f.is_flex,
        f.personalizado AS is_personalizado,
        f.is_fulfillment,
        v.demanda_id::BIGINT,
        v.demanda_numero::VARCHAR,
        v.demanda_status::VARCHAR,
        v.total_demandas::BIGINT,
        f.data_limite_envio,
        f.total_pedido,
        (v.demanda_id IS NOT NULL) AS tem_demanda,
        f.origem::VARCHAR,
        f.created_at::TIMESTAMPTZ,
        COUNT(*) OVER()::BIGINT AS total_count
    FROM filtered_pedidos f
    LEFT JOIN public.canais_venda cv ON f.canal_venda_id = cv.id
    LEFT JOIN public.installed_integrations ii ON f.marketplace_integration_id = ii.id
    LEFT JOIN public.installed_integrations bi ON f.bling_integration_id = bi.id
    LEFT JOIN public.integration_modules im ON ii.module_id = im.id
    LEFT JOIN public.situacoes_pedido sp ON f.situacao_pedido_id = sp.id
    LEFT JOIN public.v_pedido_demanda_rastreamento v ON v.pedido_id = f.id
    LEFT JOIN public.pedidos_bling pb ON pb.id = f.pedido_bling_id
    ORDER BY
        CASE WHEN p_sort = 'numero_pedido' AND p_order = 'desc' THEN NULLIF(regexp_replace(f.numero_pedido, '[^0-9]', '', 'g'), '')::BIGINT END DESC NULLS LAST,
        CASE WHEN p_sort = 'numero_pedido' AND p_order = 'asc' THEN NULLIF(regexp_replace(f.numero_pedido, '[^0-9]', '', 'g'), '')::BIGINT END ASC NULLS LAST,
        CASE WHEN p_sort = 'data_venda' AND p_order = 'desc' THEN f.data_venda END DESC NULLS LAST,
        CASE WHEN p_sort = 'data_venda' AND p_order = 'asc' THEN f.data_venda END ASC NULLS LAST,
        CASE WHEN p_sort = 'created_at' AND p_order = 'desc' THEN f.created_at END DESC NULLS LAST,
        CASE WHEN p_sort = 'created_at' AND p_order = 'asc' THEN f.created_at END ASC NULLS LAST,
        -- Default fallback
        f.data_limite_envio ASC NULLS LAST,
        f.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION public.list_pedidos_filtrados TO authenticated;
GRANT EXECUTE ON FUNCTION public.list_pedidos_filtrados TO anon;

COMMENT ON FUNCTION public.list_pedidos_filtrados IS
'Retorna lista de pedidos com filtros avancados, suporte a total_count nativo e ordenacao dinamica.';
