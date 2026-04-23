-- Add shipping_carrier column to pedidos_shopee table
-- This column will store the shipping carrier information from Shopee API
-- Used for FLEX classification (Entrega Rápida detection)

ALTER TABLE pedidos_shopee ADD COLUMN IF NOT EXISTS shipping_carrier VARCHAR(255);

-- Add comment
COMMENT ON COLUMN pedidos_shopee.shipping_carrier IS 'Shipping carrier from Shopee API. Used for FLEX classification (Entrega Rápida detection)';
