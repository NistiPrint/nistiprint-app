-- Migration: Corrigir tipos de colunas da tabela demanda_alocacoes_estoque
-- Data: 2026-03-14
-- Problema: Colunas eram UUID mas IDs do sistema são inteiros

-- 1. Remover views dependentes primeiro
DROP VIEW IF EXISTS "public"."view_alocacoes_por_demanda" CASCADE;
DROP VIEW IF EXISTS "public"."view_alocacoes_por_item" CASCADE;

-- 2. Remover funções dependentes
DROP FUNCTION IF EXISTS "public"."calcular_saldo_a_processar"(UUID, UUID, DECIMAL);
DROP FUNCTION IF EXISTS "public"."calcular_saldo_a_processar"(VARCHAR, VARCHAR, DECIMAL);
DROP FUNCTION IF EXISTS "public"."verificar_alocacao_existente"(VARCHAR);

-- 3. Alterar tipo das colunas de UUID para VARCHAR
ALTER TABLE "public"."demanda_alocacoes_estoque"
    ALTER COLUMN "demanda_id" TYPE VARCHAR(100),
    ALTER COLUMN "item_id" TYPE VARCHAR(100),
    ALTER COLUMN "produto_id" TYPE VARCHAR(100);

-- 4. Recriar índices
CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_demanda" 
    ON "public"."demanda_alocacoes_estoque" ("demanda_id");

CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_item" 
    ON "public"."demanda_alocacoes_estoque" ("item_id");

CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_produto" 
    ON "public"."demanda_alocacoes_estoque" ("produto_id");

CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_correlation" 
    ON "public"."demanda_alocacoes_estoque" ("correlation_id");

CREATE INDEX IF NOT EXISTS "idx_demanda_alocacoes_item_produto" 
    ON "public"."demanda_alocacoes_estoque" ("item_id", "produto_id") 
    WHERE "status" != 'CANCELADA';

-- 5. Recriar função calcular_saldo_a_processar
CREATE FUNCTION "public"."calcular_saldo_a_processar"(
    p_item_id VARCHAR,
    p_produto_id VARCHAR,
    p_quantidade_necessaria DECIMAL
)
RETURNS DECIMAL AS $$
DECLARE
    v_ja_alocado DECIMAL := 0;
BEGIN
    SELECT COALESCE(SUM(quantidade_alocada), 0)
    INTO v_ja_alocado
    FROM "public"."demanda_alocacoes_estoque"
    WHERE item_id = p_item_id
    AND produto_id = p_produto_id
    AND status != 'CANCELADA';

    RETURN GREATEST(p_quantidade_necessaria - v_ja_alocado, 0);
END;
$$ LANGUAGE plpgsql;

-- 6. Recriar função verificar_alocacao_existente
CREATE FUNCTION "public"."verificar_alocacao_existente"(
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

-- 7. Recriar views
CREATE VIEW "public"."view_alocacoes_por_item" AS
SELECT
    item_id,
    demanda_id,
    produto_id,
    SUM(CASE WHEN status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_alocado
FROM "public"."demanda_alocacoes_estoque"
GROUP BY item_id, demanda_id, produto_id;

CREATE VIEW "public"."view_alocacoes_por_demanda" AS
SELECT 
    demanda_id,
    COUNT(DISTINCT item_id) as itens_count,
    COUNT(DISTINCT produto_id) as produtos_count,
    SUM(CASE WHEN status != 'CANCELADA' THEN quantidade_alocada ELSE 0 END) as total_alocado_geral
FROM "public"."demanda_alocacoes_estoque"
GROUP BY demanda_id;
