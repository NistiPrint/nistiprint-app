-- ============================================
-- Migration: Correção force_fetch_all_tasks
-- ============================================
-- Remove referência a updated_at que não existe em fila_processamento_estoque
-- ============================================

CREATE OR REPLACE FUNCTION "public"."force_fetch_all_tasks"(
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
        tentativas = tentativas + 1,
        proxima_execucao_at = NOW() + INTERVAL '5 minutes'
    WHERE id IN (
        SELECT id
        FROM "public"."fila_processamento_estoque"
        WHERE status IN ('PENDENTE', 'ERRO')
        AND tipo_operacao IN ('RECONCILIACAO_ITEM', 'ITEM_TOTAL_BOM_PROCESS', 'CONSUMO_BOM', 'ESTORNO_BOM')
        AND (proxima_execucao_at IS NULL OR proxima_execucao_at <= NOW())
        AND tentativas < 5
        ORDER BY created_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION "public"."force_fetch_all_tasks"(TEXT, INTEGER) IS
'RPC para o NOVO Motor de Reconciliação (MRE) buscar e lockar tarefas da fila.
Processa apenas tarefas do tipo RECONCILIACAO_ITEM e ITEM_TOTAL_BOM_PROCESS.
Usa FOR UPDATE SKIP LOCKED para evitar concorrência entre workers.';
