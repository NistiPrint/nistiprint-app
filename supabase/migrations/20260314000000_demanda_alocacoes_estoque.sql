-- Migration: demanda_alocacoes_estoque
-- Data: 2026-03-14
-- Propósito: Controle granular de alocações de estoque por demanda para evitar duplicação de consumo

-- Tabela de controle de alocações de estoque por demanda/item
CREATE TABLE IF NOT EXISTS "public"."demanda_alocacoes_estoque" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demanda_id UUID NOT NULL,
    item_id UUID NOT NULL,
    produto_id UUID NOT NULL,
    correlation_id VARCHAR(100) NOT NULL,
    quantidade_alocada DECIMAL(10,2) NOT NULL DEFAULT 0,
    tipo_alocacao VARCHAR(50) NOT NULL, -- 'MANUAL_DASHBOARD', 'FINALIZACAO', 'PRODUCAO_JIT', 'SAIDA_DISTRIBUIDA'
    processo_origem VARCHAR(50), -- 'DASHBOARD', 'CONTROLE_PRODUCAO', 'WORKER_FINALIZACAO', 'WORKER_ETAPA'
    status VARCHAR(20) DEFAULT 'PENDENTE', -- 'PENDENTE', 'PROCESSADA', 'CANCELADA'
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    processed_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    
    -- Restrições
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
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_tipo" ON "public"."demanda_alocacoes_estoque" ("tipo_alocacao");

-- Índice composto para consultas frequentes
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_item_produto" 
    ON "public"."demanda_alocacoes_estoque" ("item_id", "produto_id") 
    WHERE "status" != 'CANCELADA';

-- Índice para consulta por correlation_id (idempotência)
CREATE UNIQUE INDEX IF NOT EXISTS "idx_demanda_alocacoes_correlation_unique" 
    ON "public"."demanda_alocacoes_estoque" ("correlation_id") 
    WHERE "status" != 'CANCELADA';

-- Comentário na tabela
COMMENT ON TABLE "public"."demanda_alocacoes_estoque IS 'Controle granular de alocações de estoque por demanda/item para evitar duplicação de consumo de componentes';
COMMENT ON COLUMN "public"."demanda_alocacoes_estoque"."tipo_alocacao" IS 'Tipo de alocação: MANUAL_DASHBOARD (alocação direta pelo usuário), FINALIZACAO (processamento de BOM na finalização), PRODUCAO_JIT (produção just-in-time por etapa), SAIDA_DISTRIBUIDA (saída distribuída para múltiplas demandas)';
COMMENT ON COLUMN "public"."demanda_alocacoes_estoque"."correlation_id" IS 'ID único para rastreabilidade e idempotência - evita processamento duplicado';
COMMENT ON COLUMN "public"."demanda_alocacoes_estoque"."status" IS 'PENDENTE: aguardando processamento, PROCESSADA: consumo de estoque realizado, CANCELADA: alocação cancelada/estornada';

-- View para consulta de alocações ativas por item
CREATE OR REPLACE VIEW "public"."view_alocacoes_por_item" AS
SELECT 
    item_id,
    demanda_id,
    produto_id,
    SUM(CASE WHEN status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_alocado,
    SUM(CASE WHEN tipo_alocacao = 'MANUAL_DASHBOARD' AND status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_manual,
    SUM(CASE WHEN tipo_alocacao = 'FINALIZACAO' AND status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_finalizacao,
    SUM(CASE WHEN tipo_alocacao = 'PRODUCAO_JIT' AND status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_jit,
    COUNT(*) FILTER (WHERE status = 'PENDENTE') as pendentes_count
FROM "public"."demanda_alocacoes_estoque"
GROUP BY item_id, demanda_id, produto_id;

-- View para consulta de alocações por demanda
CREATE OR REPLACE VIEW "public"."view_alocacoes_por_demanda" AS
SELECT 
    demanda_id,
    COUNT(DISTINCT item_id) as itens_count,
    COUNT(DISTINCT produto_id) as produtos_count,
    SUM(CASE WHEN status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_alocado_geral,
    SUM(CASE WHEN tipo_alocacao = 'MANUAL_DASHBOARD' AND status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_manual,
    SUM(CASE WHEN status = 'PENDENTE' THEN quantidade_alocada ELSE 0 END) as total_pendente
FROM "public"."demanda_alocacoes_estoque"
GROUP BY demanda_id;

-- Função para verificar se alocação já existe (idempotência)
CREATE OR REPLACE FUNCTION "public"."verificar_alocacao_existente"(
    p_correlation_id VARCHAR
)
RETURNS BOOLEAN AS $$
DECLARE
    v_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM "public"."demanda_alocacoes_estoque"
        WHERE correlation_id = p_correlation_id
        AND status != 'CANCELADA'
    ) INTO v_exists;
    
    RETURN v_exists;
END;
$$ LANGUAGE plpgsql;

-- Função para marcar alocação como processada
CREATE OR REPLACE FUNCTION "public"."marcar_alocacao_processada"(
    p_correlation_id VARCHAR
)
RETURNS VOID AS $$
BEGIN
    UPDATE "public"."demanda_alocacoes_estoque"
    SET status = 'PROCESSADA',
        processed_at = NOW()
    WHERE correlation_id = p_correlation_id
    AND status = 'PENDENTE';
END;
$$ LANGUAGE plpgsql;

-- Função para cancelar alocação
CREATE OR REPLACE FUNCTION "public"."cancelar_alocacao"(
    p_correlation_id VARCHAR,
    p_motivo TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE "public"."demanda_alocacoes_estoque"
    SET status = 'CANCELADA',
        cancelled_at = NOW(),
        metadata = metadata || jsonb_build_object('motivo_cancelamento', p_motivo)
    WHERE correlation_id = p_correlation_id
    AND status != 'CANCELADA';
END;
$$ LANGUAGE plpgsql;

-- Função para buscar saldo a processar (diferença entre necessário e já alocado)
CREATE OR REPLACE FUNCTION "public"."calcular_saldo_a_processar"(
    p_item_id UUID,
    p_produto_id UUID,
    p_quantidade_necessaria DECIMAL
)
RETURNS DECIMAL AS $$
DECLARE
    v_ja_alocado DECIMAL := 0;
    v_saldo DECIMAL;
BEGIN
    -- Soma todas as alocações não canceladas para este item+produto
    SELECT COALESCE(SUM(quantidade_alocada), 0)
    INTO v_ja_alocado
    FROM "public"."demanda_alocacoes_estoque"
    WHERE item_id = p_item_id
    AND produto_id = p_produto_id
    AND status != 'CANCELADA';
    
    -- Calcula saldo restante
    v_saldo := p_quantidade_necessaria - v_ja_alocado;
    
    -- Retorna apenas se positivo, senão 0
    RETURN GREATEST(v_saldo, 0);
END;
$$ LANGUAGE plpgsql;

-- Grants (ajustar conforme necessidade)
-- ALTER TABLE "public"."demanda_alocacoes_estoque" OWNER TO postgres;
-- GRANT ALL ON "public"."demanda_alocacoes_estoque" TO authenticated;
-- GRANT SELECT ON "public"."view_alocacoes_por_item" TO authenticated;
-- GRANT SELECT ON "public"."view_alocacoes_por_demanda" TO authenticated;
