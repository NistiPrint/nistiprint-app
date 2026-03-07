-- Migração para Implementação de Processamento Híbrido de Estoque
-- Data: 2026-03-05

-- 1. Adicionar colunas de rastreabilidade na movimentacoes_estoque
ALTER TABLE "public"."movimentacoes_estoque" 
ADD COLUMN IF NOT EXISTS "correlation_id" UUID DEFAULT gen_random_uuid(),
ADD COLUMN IF NOT EXISTS "origem_tipo" INTEGER;

CREATE INDEX IF NOT EXISTS "idx_movimentacoes_correlation_id" ON "public"."movimentacoes_estoque" ("correlation_id");
CREATE INDEX IF NOT EXISTS "idx_movimentacoes_origem_tipo" ON "public"."movimentacoes_estoque" ("origem_tipo");

-- 2. Garantir que a fila_processamento_estoque exista com a estrutura necessária
CREATE TABLE IF NOT EXISTS "public"."fila_processamento_estoque" (
    "id" UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    "demanda_id" INTEGER,
    "item_id" INTEGER,
    "produto_id" INTEGER, -- Produto principal (1º nível) que gerou a necessidade
    "quantidade" NUMERIC(15,4) NOT NULL,
    "tipo_operacao" VARCHAR(50) DEFAULT 'CONSUMO_BOM', -- CONSUMO_BOM, ESTORNO_BOM
    "correlation_id" UUID NOT NULL,
    "user_id" VARCHAR(255),
    "status" VARCHAR(20) DEFAULT 'PENDENTE', -- PENDENTE, PROCESSANDO, CONCLUIDO, ERRO
    "tentativas" INTEGER DEFAULT 0,
    "locked_at" TIMESTAMP WITH TIME ZONE,
    "worker_id" VARCHAR(100),
    "processed_at" TIMESTAMP WITH TIME ZONE,
    "proxima_execucao_at" TIMESTAMP WITH TIME ZONE,
    "mensagem_erro" TEXT,
    "created_at" TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    "updated_at" TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_fila_estoque_status" ON "public"."fila_processamento_estoque" ("status") WHERE "status" = 'PENDENTE';
CREATE INDEX IF NOT EXISTS "idx_fila_estoque_correlation_id" ON "public"."fila_processamento_estoque" ("correlation_id");

-- 3. Criar a RPC registrar_movimentacao_primaria
-- Esta função garante que o 1º nível seja persistido atomicamente no Postgres
CREATE OR REPLACE FUNCTION "public"."registrar_movimentacao_primaria"(
    p_produto_id INTEGER,
    p_deposito_id INTEGER,
    p_tipo_movimentacao VARCHAR(50),
    p_quantidade NUMERIC(15,4),
    p_motivo TEXT,
    p_origem_tipo INTEGER,
    p_usuario_id INTEGER,
    p_documento_referencia VARCHAR(255) DEFAULT NULL,
    p_correlation_id UUID DEFAULT gen_random_uuid()
) RETURNS UUID AS $$
DECLARE
    v_saldo_atual NUMERIC(15,4);
    v_saldo_novo NUMERIC(15,4);
    v_mov_id INTEGER;
BEGIN
    -- 1. Obter e atualizar saldo na estoque_atual
    -- Tenta pegar o saldo atual (Lock for Update para evitar race conditions)
    SELECT saldo_atual INTO v_saldo_atual 
    FROM "public"."estoque_atual" 
    WHERE produto_id = p_produto_id AND deposito_id = p_deposito_id
    FOR UPDATE;

    IF v_saldo_atual IS NULL THEN
        v_saldo_atual := 0;
        INSERT INTO "public"."estoque_atual" (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
        VALUES (p_produto_id, p_deposito_id, p_quantidade, NOW());
        v_saldo_novo := p_quantidade;
    ELSE
        v_saldo_novo := v_saldo_atual + p_quantidade;
        UPDATE "public"."estoque_atual" 
        SET saldo_atual = v_saldo_novo, ultima_atualizacao = NOW(), updated_at = NOW()
        WHERE produto_id = p_produto_id AND deposito_id = p_deposito_id;
    END IF;

    -- 2. Inserir na movimentacoes_estoque
    INSERT INTO "public"."movimentacoes_estoque" (
        produto_id, deposito_id, tipo_movimentacao, quantidade, 
        saldo_antes, saldo_depois, motivo, usuario_id, 
        documento_referencia, correlation_id, origem_tipo, data_movimentacao
    ) VALUES (
        p_produto_id, p_deposito_id, p_tipo_movimentacao, p_quantidade,
        v_saldo_atual, v_saldo_novo, p_motivo, p_usuario_id,
        p_documento_referencia, p_correlation_id, p_origem_tipo, NOW()
    ) RETURNING id INTO v_mov_id;

    -- 3. Inserir na fila para processamento de insumos (se for produção/consumo)
    -- Origens que disparam JIT: DASHBOARD_PRODUCAO_INCREMENTAL (1), CONTROLE_PRODUCAO_LOTE (3)
    IF p_origem_tipo IN (1, 3) THEN
        INSERT INTO "public"."fila_processamento_estoque" (
            produto_id, quantidade, correlation_id, user_id, status, tipo_operacao
        ) VALUES (
            p_produto_id, ABS(p_quantidade), p_correlation_id, p_usuario_id::TEXT, 'PENDENTE', 'CONSUMO_BOM'
        );
    ELSIF p_origem_tipo = 2 THEN -- ESTORNO
        INSERT INTO "public"."fila_processamento_estoque" (
            produto_id, quantidade, correlation_id, user_id, status, tipo_operacao
        ) VALUES (
            p_produto_id, ABS(p_quantidade), p_correlation_id, p_usuario_id::TEXT, 'PENDENTE', 'ESTORNO_BOM'
        );
    END IF;

    RETURN p_correlation_id;
END;
$$ LANGUAGE plpgsql;

-- 4. RPC para o Worker (Consumo atômico da fila)
CREATE OR REPLACE FUNCTION "public"."fetch_and_lock_stock_tasks"(
    p_worker_id VARCHAR(100),
    p_limit INTEGER DEFAULT 10
) RETURNS SETOF "public"."fila_processamento_estoque" AS $$
BEGIN
    RETURN QUERY
    UPDATE "public"."fila_processamento_estoque"
    SET 
        status = 'PROCESSANDO',
        locked_at = NOW(),
        worker_id = p_worker_id,
        tentativas = tentativas + 1
    WHERE id IN (
        SELECT id 
        FROM "public"."fila_processamento_estoque"
        WHERE status IN ('PENDENTE', 'ERRO')
        AND (proxima_execucao_at IS NULL OR proxima_execucao_at <= NOW())
        AND tentativas < 5
        ORDER BY created_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;
