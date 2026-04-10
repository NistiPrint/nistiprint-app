-- ============================================
-- Migração: Adicionar coluna personalizado na tabela pedidos
-- Data: 2026-04-09
-- Objetivo: Permitir flag de personalizado no nível do pedido (modelo unificado)
-- ============================================

ALTER TABLE pedidos 
ADD COLUMN IF NOT EXISTS personalizado BOOLEAN DEFAULT false;

-- Índice parcial (só interessa quando true)
CREATE INDEX IF NOT EXISTS idx_pedidos_personalizado 
ON pedidos(personalizado) WHERE personalizado = true;
