-- Função para buscar pedidos prontos para consolidação com filtros avançados
CREATE OR REPLACE FUNCTION get_pedidos_para_consolidar(
    p_plataforma_id INTEGER DEFAULT NULL,
    p_is_flex BOOLEAN DEFAULT NULL,
    p_data_inicio TIMESTAMPTZ DEFAULT NULL,
    p_data_fim TIMESTAMPTZ DEFAULT NULL,
    p_search TEXT DEFAULT NULL
)
RETURNS SETOF public.view_pedidos_para_consolidar AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM public.view_pedidos_para_consolidar v
    WHERE 
        (p_plataforma_id IS NULL OR v.canal_venda_id = p_plataforma_id) AND
        (p_is_flex IS NULL OR v.is_flex = p_is_flex) AND
        (p_data_inicio IS NULL OR v.data_limite_envio >= p_data_inicio) AND
        (p_data_fim IS NULL OR v.data_limite_envio <= p_data_fim) AND
        (p_search IS NULL OR 
            v.cliente_nome ILIKE '%' || p_search || '%' OR 
            v.numero_pedido ILIKE '%' || p_search || '%' OR 
            v.codigo_pedido_externo ILIKE '%' || p_search || '%'
        );
END;
$$ LANGUAGE plpgsql STABLE;
