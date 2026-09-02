-- 1. Adicionar coluna de prioridade na fila de estoque
ALTER TABLE "public"."fila_processamento_estoque" 
ADD COLUMN IF NOT EXISTS "prioridade" INTEGER DEFAULT 10;

-- 2. Atualizar RPC de consumo para ordenar por prioridade
CREATE OR REPLACE FUNCTION "public"."fetch_and_lock_stock_tasks"(
    p_worker_id VARCHAR(100),
    p_limit INTEGER DEFAULT 10
) RETURNS SETOF "public"."fila_processamento_estoque" AS $$
BEGIN
    RETURN QUERY
    UPDATE "public"."fila_processamento_estoque"
    SET 
        status = 'PROCESSANDO',
        locked_at = NOW(),
        worker_id = p_worker_id,
        tentativas = tentativas + 1
    WHERE id IN (
        SELECT id
        FROM "public"."fila_processamento_estoque"
        WHERE status IN ('PENDENTE', 'ERRO')
        AND (proxima_execucao_at IS NULL OR proxima_execucao_at <= NOW())
        AND tentativas < 5
        ORDER BY prioridade ASC, created_at ASC 
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;

-- 3. Atualizar View de Vendas e Funções Dependentes
-- Usamos CASCADE para remover a view e objetos que dependem do seu tipo (como a função get_pedidos_para_consolidar)
DROP VIEW IF EXISTS public.view_pedidos_para_consolidar CASCADE;

CREATE VIEW public.view_pedidos_para_consolidar AS
SELECT
    p.id AS pedido_id,
    p.numero_pedido,
    p.codigo_pedido_externo,
    p.origem,
    p.cliente_nome,
    p.cliente_telefone,
    p.is_flex,
    p.data_limite_envio,
    p.total_pedido,
    p.situacao_pedido_id,
    s.nome AS situacao_nome,
    p.canal_venda_id,
    cv.nome AS plataforma_nome,
    p.servico_logistico,
    (
        SELECT jsonb_agg(jsonb_build_object(
            'sku_externo', i.sku_externo,
            'descricao', i.descricao,
            'quantidade', i.quantidade
        ))
        FROM public.itens_pedido i
        WHERE i.pedido_id = p.id
    ) AS itens,
    EXISTS (
        SELECT 1 FROM public.demandas_item_origem dio 
        WHERE dio.pedido_externo_id = p.codigo_pedido_externo
    ) AS has_demanda
FROM public.pedidos p
LEFT JOIN public.situacoes_pedido s ON p.situacao_pedido_id = s.id
LEFT JOIN public.canais_venda cv ON p.canal_venda_id = cv.id
WHERE p.situacao_pedido_id IN (1, 2);

-- 4. Re-criar a função get_pedidos_para_consolidar (que foi removida pelo CASCADE)
CREATE OR REPLACE FUNCTION public.get_pedidos_para_consolidar(
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
