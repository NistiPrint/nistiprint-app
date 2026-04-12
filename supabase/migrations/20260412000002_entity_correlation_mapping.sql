-- Migration para rastreamento end-to-end com correlation_id
-- Created at: 2026-04-12
-- Description: Tabela para mapear entidades (pedidos, demandas, etc.) para correlation_ids

CREATE TABLE IF NOT EXISTS entity_correlation_mapping (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    correlation_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT unique_entity_correlation UNIQUE (entity_type, entity_id, correlation_id)
);

-- Índices para busca eficiente
CREATE INDEX IF NOT EXISTS idx_entity_correlation_entity ON entity_correlation_mapping(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_correlation_correlation ON entity_correlation_mapping(correlation_id);

-- Grant permissions
GRANT ALL ON TABLE entity_correlation_mapping TO anon;
GRANT ALL ON TABLE entity_correlation_mapping TO authenticated;
GRANT ALL ON TABLE entity_correlation_mapping TO service_role;
