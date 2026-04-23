-- Migration: demanda_alocacoes_estoque
-- Data: 2026-03-14
-- Propósito: Controle granular de alocações de estoque por demanda/item para evitar duplicação de consumo

-- Tabela de controle de alocações de estoque por demanda/item
CREATE TABLE IF NOT EXISTS "public"."demanda_alocacoes_estoque" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demanda_id UUID NOT NULL,
    item_id UUID NOT NULL,
    produto_id UUID NOT NULL,
    correlation_id VARCHAR(100) NOT NULL,
    quantidade_alocada DECIMAL(10,2) NOT NULL DEFAULT 0,
    tipo_alocacao VARCHAR(50) NOT NULL,
    processo_origem VARCHAR(50),
    status VARCHAR(20) DEFAULT 'PENDENTE',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    
    CONSTRAINT chk_tipo_alocacao CHECK (tipo_alocacao IN ('MANUAL_DASHBOARD', 'FINALIZACAO', 'PRODUCAO_JIT', 'SAIDA_DISTRIBUIDA')),
    CONSTRAINT chk_status CHECK (status IN ('PENDENTE', 'PROCESSADA', 'CANCELADA')),
    CONSTRAINT chk_quantidade CHECK (quantidade_alocada >= 0)
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_demanda" ON "public"."demanda_alocacoes_estoque" ("demanda_id");
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_item" ON "public"."demanda_alocacoes_estoque" ("item_id");
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_produto" ON "public"."demanda_alocacoes_estoque" ("produto_id");
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_correlation" ON "public"."demanda_alocacoes_estoque" ("correlation_id");
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_status" ON "public"."demanda_alocacoes_estoque" ("status") WHERE "status" = 'PENDENTE';
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_item_produto" 
    ON "public"."demanda_alocacoes_estoque" ("item_id", "produto_id") 
    WHERE "status" != 'CANCELADA';

-- View para consulta de alocações ativas por item
CREATE OR REPLACE VIEW "public"."view_alocacoes_por_item" AS
SELECT 
    item_id,
    demanda_id,
    produto_id,
    SUM(CASE WHEN status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_alocado
FROM "public"."demanda_alocacoes_estoque"
GROUP BY item_id, demanda_id, produto_id;

-- Função para calcular saldo a processar
CREATE OR REPLACE FUNCTION "public"."calcular_saldo_a_processar"(
    p_item_id UUID,
    p_produto_id VARCHAR,
    p_quantidade_necessaria DECIMAL
)
RETURNS DECIMAL AS $$
DECLARE
    v_ja_alocado DECIMAL := 0;
    v_saldo DECIMAL;
BEGIN
    SELECT COALESCE(SUM(quantidade_alocada), 0)
    INTO v_ja_alocado
    FROM "public"."demanda_alocacoes_estoque"
    WHERE item_id = p_item_id
    AND produto_id = p_produto_id
    AND status != 'CANCELADA';
    
    v_saldo := p_quantidade_necessaria - v_ja_alocado;
    RETURN GREATEST(v_saldo, 0);
END;
$$ LANGUAGE plpgsql;

-- Função para verificar alocação existente
CREATE OR REPLACE FUNCTION "public"."verificar_alocacao_existente"(
    p_correlation_id VARCHAR
)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM "public"."demanda_alocacoes_estoque"
        WHERE correlation_id = p_correlation_id
        AND status != 'CANCELADA'
    );
END;
$$ LANGUAGE plpgsql;
