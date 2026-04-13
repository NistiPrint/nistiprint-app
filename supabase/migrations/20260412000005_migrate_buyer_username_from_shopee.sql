-- Migração: Obter buyer_username da tabela pedidos_shopee
-- Data: 2026-04-12
-- Objetivo: Enriquecer a tabela pedidos com buyer_username de pedidos_shopee
--           para garantir que todos os pedidos Shopee tenham esse dado populado

-- Atualizar buyer_username na tabela pedidos usando dados de pedidos_shopee
UPDATE pedidos p
SET buyer_username = s.informacoes_comprador->>'username'
FROM pedidos_shopee s
WHERE p.codigo_pedido_externo = s.codigo_pedido
  AND s.informacoes_comprador->>'username' IS NOT NULL
  AND s.informacoes_comprador->>'username' != ''
  AND (p.buyer_username IS NULL OR p.buyer_username = '');

-- Atualizar marketplace_order_id se estiver vazio
UPDATE pedidos p
SET marketplace_order_id = s.codigo_pedido
FROM pedidos_shopee s
WHERE p.codigo_pedido_externo = s.codigo_pedido
  AND (p.marketplace_order_id IS NULL OR p.marketplace_order_id = '');

-- Atualizar shipping_carrier se estiver vazio e tiver dados em pedidos_shopee
-- Nota: A tabela pedidos_shopee não tem shipping_carrier explícito, mas pode estar em outros campos
-- Esta query é preparada caso adicionar shipping_carrier à tabela pedidos_shopee no futuro
