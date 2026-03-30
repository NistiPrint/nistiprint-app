-- Migration: 20260325000001_fix_legacy_worker_rpc.sql
-- Propósito: Impedir que o worker legado consuma as tarefas do novo Motor de Reconciliação (MRE).

DROP FUNCTION IF EXISTS "public"."fetch_and_lock_stock_tasks"(text, integer);
DROP FUNCTION IF EXISTS "public"."fetch_and_lock_stock_tasks"(character varying, integer);

CREATE OR REPLACE FUNCTION "public"."fetch_and_lock_stock_tasks"(
    p_worker_id TEXT,
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
        AND tipo_operacao NOT IN ('RECONCILIACAO_ITEM', 'CONSUMO_BOM', 'ESTORNO_BOM')
        AND (proxima_execucao_at IS NULL OR proxima_execucao_at <= NOW())
        AND tentativas < 5
        ORDER BY created_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;
