-- Migration: 20260325000002_create_force_fetch_tasks_rpc.sql
-- Data: 2026-03-25
-- Propósito: Criar RPC force_fetch_all_tasks para o novo Motor de Reconciliação (MRE)
--
-- Esta RPC é consumida pelo método processar_fila_unificada() do MotorReconciliacaoEstoque
-- para buscar tarefas de RECONCILIACAO_ITEM e ITEM_TOTAL_BOM_PROCESS.
--
-- Diferença para fetch_and_lock_stock_tasks():
-- - fetch_and_lock_stock_tasks: worker LEGADO, processa CONSUMO_BOM/ESTORNO_BOM
-- - force_fetch_all_tasks: worker NOVO (MRE), processa RECONCILIACAO_ITEM/ITEM_TOTAL_BOM_PROCESS

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
        updated_at = NOW()
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

-- FIM DA MIGRATION
