-- ============================================
-- Migração: Adicionar item_pedido_id em personalizacoes_pedido
-- Data: 2026-04-10
-- Objetivo: Permitir match direto entre personalização e item_pedido
--           (evitando match frágil apenas por descrição).
-- ============================================

-- 1. Adicionar coluna item_pedido_id (nullable para compatibilidade retroativa)
ALTER TABLE personalizacoes_pedido
ADD COLUMN IF NOT EXISTS item_pedido_id integer;

-- 2. Índice para lookup rápido por item_pedido_id
CREATE INDEX IF NOT EXISTS idx_personalizacoes_item_pedido_id
ON personalizacoes_pedido(item_pedido_id)
WHERE item_pedido_id IS NOT NULL;

-- 3. Comentário
COMMENT ON COLUMN personalizacoes_pedido.item_pedido_id IS
    'Referência direta ao item em itens_pedido.id. Substitui match por descrição.';
