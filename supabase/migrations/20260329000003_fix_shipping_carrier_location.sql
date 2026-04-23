-- =====================================================
-- Migration: Corrige shipping_carrier para servico_logistico
-- =====================================================
-- Data: 2026-03-29
-- Descrição:
--   - Move shipping_carrier de informacoes_cliente para servico_logistico
--   - shipping_carrier é dado logístico, não do cliente
-- =====================================================

-- 1. Mover shipping_carrier de informacoes_cliente para servico_logistico
-- =====================================================
-- Atualizar servico_logistico com o valor de informacoes_cliente->>'shipping_carrier'
-- apenas se servico_logistico estiver vazio
UPDATE public.pedidos
SET servico_logistico = informacoes_cliente->>'shipping_carrier'
WHERE informacoes_cliente->>'shipping_carrier' IS NOT NULL
  AND informacoes_cliente->>'shipping_carrier' <> ''
  AND (servico_logistico IS NULL OR servico_logistico = '');

-- 2. Remover shipping_carrier de informacoes_cliente (não é mais necessário lá)
-- =====================================================
-- Atualizar JSONB para remover a chave shipping_carrier
UPDATE public.pedidos
SET informacoes_cliente = informacoes_cliente - 'shipping_carrier'
WHERE informacoes_cliente ? 'shipping_carrier';

-- 3. Recalcular is_flex para todos os pedidos com servico_logistico
-- =====================================================
-- Usar a função normalize_text_for_flex (criada na migration anterior)
-- para garantir que is_flex esteja correto após a migração
UPDATE public.pedidos
SET is_flex = (
    CASE
        WHEN public.normalize_text_for_flex(servico_logistico) LIKE '%ENTREGA_RAPIDA%' 
             OR public.normalize_text_for_flex(servico_logistico) LIKE '%ENTREGARAPIDA%'
        THEN TRUE
        ELSE FALSE
    END
)
WHERE servico_logistico IS NOT NULL 
  AND servico_logistico <> '';

-- =====================================================
-- RESUMO
-- =====================================================
-- ✅ shipping_carrier movido para servico_logistico
-- ✅ shipping_carrier removido de informacoes_cliente
-- ✅ is_flex recalculado para todos os pedidos
-- =====================================================
-- Agora o modelo de dados está correto:
-- - servico_logistico: dado logístico (shipping_carrier)
-- - informacoes_cliente: apenas dados do cliente
-- - is_flex: derivado de servico_logistico
-- =====================================================
