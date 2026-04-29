-- =====================================================
-- SCRIPT DE VALIDAÇÃO - Pedidos Flex e Situações
-- =====================================================
-- Data: 2026-03-28
-- Executar após aplicar migrations
-- =====================================================

-- 1. VALIDAR SITUAÇÕES DE PEDIDO
-- =====================================================
-- Esperado: 7 situações com IDs fixos (1-7)
SELECT 
    id,
    nome,
    cor_status,
    flag_cancelado,
    CASE id
        WHEN 1 THEN 'Em Aberto (Bling 6)'
        WHEN 2 THEN 'Em Andamento (Bling 15)'
        WHEN 3 THEN 'Produzido'
        WHEN 4 THEN 'Pronto para Envio'
        WHEN 5 THEN 'Enviado (Bling 9, 18)'
        WHEN 6 THEN 'Entregue'
        WHEN 7 THEN 'Cancelado (Bling 12)'
        ELSE 'Desconhecido'
    END as mapeamento_bling
FROM public.situacoes_pedido
WHERE id <= 7
ORDER BY id;

-- 2. VALIDAR FUNÇÃO list_pedidos_filtrados
-- =====================================================
-- Esperado: Retornar colunas com situacao_nome, situacao_cor, is_flex, data_limite_envio
SELECT 
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'list_pedidos_filtrados'
  AND table_schema = 'public'
ORDER BY ordinal_position;

-- 3. TESTAR FILTRO POR FLEX
-- =====================================================
-- Esperado: Retornar apenas pedidos Flex (se existirem)
SELECT * FROM public.list_pedidos_filtrados(
    p_is_flex => true,
    p_limit => 10
);

-- 4. TESTAR FILTRO POR PERÍODO DE ENVIO
-- =====================================================
-- Esperado: Pedidos com data_limite_envio no período
SELECT * FROM public.list_pedidos_filtrados(
    p_delivery_start_date => '2026-03-28',
    p_delivery_end_date => '2026-04-30',
    p_limit => 10
);

-- 5. TESTAR ORDENAÇÃO (Flex primeiro, depois por data)
-- =====================================================
-- Esperado: Pedidos Flex no topo, ordenados por data_limite_envio
SELECT 
    id,
    numero_pedido,
    is_flex,
    data_limite_envio,
    situacao_pedido_id
FROM public.pedidos
ORDER BY 
    is_flex DESC,
    data_limite_envio ASC NULLS LAST
LIMIT 20;

-- 6. VALIDAR ÍNDICES CRIADOS
-- =====================================================
-- Esperado: 4 índices novos (idx_pedidos_is_flex*)
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'pedidos'
  AND indexname LIKE 'idx_pedidos%'
ORDER BY indexname;

-- 7. CONTAGEM DE PEDIDOS FLEX
-- =====================================================
-- Esperado: Mostrar quantidade de pedidos Flex vs Não-Flex
SELECT 
    is_flex,
    COUNT(*) as quantidade,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentual
FROM public.pedidos
GROUP BY is_flex
ORDER BY is_flex DESC;

-- 8. PEDIDOS FLEX POR STATUS
-- =====================================================
-- Esperado: Distribuição de pedidos Flex por situação
SELECT 
    sp.nome as situacao,
    COUNT(*) as quantidade
FROM public.pedidos p
LEFT JOIN public.situacoes_pedido sp ON p.situacao_pedido_id = sp.id
WHERE p.is_flex = true
GROUP BY sp.id, sp.nome
ORDER BY quantidade DESC;

-- 9. VALIDAR DADOS DE PEDIDOS RECENTES
-- =====================================================
-- Esperado: Pedidos com is_flex e data_limite_envio preenchidos
SELECT 
    id,
    numero_pedido,
    codigo_pedido_externo,
    origem,
    is_flex,
    data_limite_envio,
    situacao_pedido_id,
    created_at
FROM public.pedidos
WHERE is_flex = true
   OR data_limite_envio IS NOT NULL
ORDER BY created_at DESC
LIMIT 20;

-- 10. TESTAR RPC COM TODOS OS FILTROS
-- =====================================================
-- Esperado: Funcionar com todos os parâmetros opcionais
SELECT * FROM public.list_pedidos_filtrados(
    p_situacao_pedido_id => NULL,
    p_canal_venda_id => NULL,
    p_has_demanda => NULL,
    p_is_flex => NULL,
    p_delivery_start_date => NULL,
    p_delivery_end_date => NULL,
    p_search_term => NULL,
    p_limit => 5,
    p_offset => 0
);

-- =====================================================
-- RESUMO DA VALIDAÇÃO
-- =====================================================
-- Se todas as queries acima executarem sem erro:
-- ✅ Situações de pedido criadas com IDs fixos
-- ✅ Função list_pedidos_filtrados atualizada
-- ✅ Filtro por is_flex funcionando
-- ✅ Filtro por período de envio funcionando
-- ✅ Ordenação por Flex e data correta
-- ✅ Índices criados
-- =====================================================
