-- Migração para adicionar colunas explícitas à tabela pedidos
-- Migrar dados críticos do JSON informacoes_cliente para colunas explícitas

-- Adicionar colunas explícitas para dados do marketplace
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS buyer_username VARCHAR(255);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS marketplace_order_id VARCHAR(255);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS shipping_carrier VARCHAR(255);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS contact_marketplace_id VARCHAR(255);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS message_to_seller TEXT;

-- Adicionar comentários para documentar as colunas
COMMENT ON COLUMN pedidos.buyer_username IS 'Nome de usuário do marketplace (Shopee, ML, etc)';
COMMENT ON COLUMN pedidos.marketplace_order_id IS 'ID do pedido no marketplace externo';
COMMENT ON COLUMN pedidos.shipping_carrier IS 'Serviço logístico do marketplace (ex: Entrega Rápida)';
COMMENT ON COLUMN pedidos.contact_marketplace_id IS 'ID de contato no marketplace';
COMMENT ON COLUMN pedidos.message_to_seller IS 'Mensagem do comprador ao vendedor (Shopee)';
