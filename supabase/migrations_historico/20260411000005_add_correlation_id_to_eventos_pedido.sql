-- Add correlation_id column to eventos_pedido for tracking
-- This enables end-to-end tracing of order processing workflows

ALTER TABLE eventos_pedido 
ADD COLUMN IF NOT EXISTS correlation_id TEXT;

-- Create index for efficient correlation_id lookups
CREATE INDEX IF NOT EXISTS idx_eventos_pedido_correlation_id 
ON eventos_pedido(correlation_id);

-- Add comment explaining the purpose
COMMENT ON COLUMN eventos_pedido.correlation_id IS 'Correlation ID for end-to-end tracing of order processing workflows';
