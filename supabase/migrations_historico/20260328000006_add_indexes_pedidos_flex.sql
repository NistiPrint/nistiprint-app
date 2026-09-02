-- Migration: Adiciona índices para otimizar filtros de pedidos Flex e data de envio
-- Data: 2026-03-28
--
-- Problema: Consultas por is_flex e data_limite_envio podem ser lentas sem índices
-- Solução: Criar índices compostos para os filtros mais comuns

-- Índice para filtro por is_flex (pedidos de entrega rápida)
-- Útil para: "SELECT * FROM pedidos WHERE is_flex = true"
CREATE INDEX IF NOT EXISTS idx_pedidos_is_flex 
ON public.pedidos(is_flex) 
WHERE is_flex = true;

-- Índice composto para pedidos Flex ordenados por data de envio
-- Útil para: "SELECT * FROM pedidos WHERE is_flex = true ORDER BY data_limite_envio"
CREATE INDEX IF NOT EXISTS idx_pedidos_is_flex_data_envio 
ON public.pedidos(is_flex, data_limite_envio ASC NULLS LAST) 
WHERE is_flex = true;

-- Índice para filtro por data_limite_envio (usado em filtros de período)
-- Útil para: "SELECT * FROM pedidos WHERE data_limite_envio BETWEEN X AND Y"
CREATE INDEX IF NOT EXISTS idx_pedidos_data_limite_envio 
ON public.pedidos(data_limite_envio ASC NULLS LAST);

-- Índice composto para a view de consolidação (status + flex + data)
-- Útil para: Filtros combinados de status, flex e período de entrega
CREATE INDEX IF NOT EXISTS idx_pedidos_status_flex_data 
ON public.pedidos(situacao_pedido_id, is_flex, data_limite_envio ASC NULLS LAST);

-- Comentário nos índices
COMMENT ON INDEX public.idx_pedidos_is_flex IS 
'Índice parcial para pedidos Flex (entrega rápida) - otimiza listagem de pedidos prioritários';

COMMENT ON INDEX public.idx_pedidos_is_flex_data_envio IS 
'Índice composto para pedidos Flex ordenados por data de envio - usado na tela de consolidação';

COMMENT ON INDEX public.idx_pedidos_data_limite_envio IS 
'Índice para filtro por período de data de envio';

COMMENT ON INDEX public.idx_pedidos_status_flex_data IS 
'Índice composto para filtros combinados de status, Flex e data de envio';

-- Analisar tabela para atualizar estatísticas do query planner
ANALYZE public.pedidos;
