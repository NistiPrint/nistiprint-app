-- =============================================================
-- CLEANUP: logs, eventos e historico operacional antigo
-- Retencao padrao: 10 dias
-- =============================================================
--
-- Uso:
--   1. Rode como esta para preview. Nenhum dado persistente sera alterado.
--   2. Revise o relatorio final.
--   3. Para executar de fato, altere v_execute para true e rode novamente.
--
-- Observacoes:
--   - O cutoff e truncado para o inicio do dia para tornar o script
--     idempotente quando rodado mais de uma vez no mesmo dia.
--   - estoque_atual nao e apagado. Antes de limpar movimentacoes antigas,
--     o script cria um movimento BALANCO por produto/deposito como saldo de
--     abertura no cutoff.
--   - eventos_auditoria e entidades centrais de negocio ficam fora do escopo.
-- =============================================================

DO $$
DECLARE
    v_execute boolean := false;
    v_retention_days integer := 10;
    v_cutoff timestamptz := date_trunc('day', now() - make_interval(days => 10));
    v_cutoff_ts timestamp := (date_trunc('day', now() - make_interval(days => 10)))::timestamp;
    v_cutoff_key text := to_char(date_trunc('day', now() - make_interval(days => 10)), 'YYYYMMDD');
    v_mode text;
    v_count bigint;
    v_step integer := 0;
    r record;
BEGIN
    v_mode := CASE WHEN v_execute THEN 'delete' ELSE 'preview' END;

    CREATE TEMP TABLE IF NOT EXISTS cleanup_old_log_records_results (
        step_no integer,
        action text,
        table_name text,
        rule text,
        mode text,
        cutoff timestamptz,
        rows_affected bigint,
        status text
    ) ON COMMIT PRESERVE ROWS;

    TRUNCATE TABLE cleanup_old_log_records_results;

    -- ---------------------------------------------------------
    -- Referencias que precisam ser removidas antes dos deletes.
    -- ---------------------------------------------------------
    IF to_regclass('public.estoque_consolidado') IS NOT NULL
       AND to_regclass('public.eventos_producao_v2') IS NOT NULL THEN
        SELECT count(*)
          INTO v_count
          FROM public.estoque_consolidado ec
         WHERE ec.ultimo_processamento_evento_id IS NOT NULL
           AND EXISTS (
                SELECT 1
                  FROM public.eventos_producao_v2 ep
                 WHERE ep.id = ec.ultimo_processamento_evento_id
                   AND ep.created_at < v_cutoff
           );

        IF v_execute THEN
            UPDATE public.estoque_consolidado ec
               SET ultimo_processamento_evento_id = NULL,
                   updated_at = now()
             WHERE ec.ultimo_processamento_evento_id IS NOT NULL
               AND EXISTS (
                    SELECT 1
                      FROM public.eventos_producao_v2 ep
                     WHERE ep.id = ec.ultimo_processamento_evento_id
                       AND ep.created_at < v_cutoff
               );
            GET DIAGNOSTICS v_count = ROW_COUNT;
        END IF;

        v_step := v_step + 1;
        INSERT INTO cleanup_old_log_records_results
        VALUES (
            v_step,
            'update_fk',
            'estoque_consolidado',
            'ultimo_processamento_evento_id -> NULL quando aponta para eventos_producao_v2 antigo',
            v_mode,
            v_cutoff,
            v_count,
            'ok'
        );
    ELSE
        v_step := v_step + 1;
        INSERT INTO cleanup_old_log_records_results
        VALUES (
            v_step,
            'update_fk',
            'estoque_consolidado',
            'tabela estoque_consolidado ou eventos_producao_v2 ausente',
            v_mode,
            v_cutoff,
            0,
            'skipped'
        );
    END IF;

    -- ---------------------------------------------------------
    -- Criar BALANCO de abertura para estoque antes de remover
    -- movimentacoes antigas.
    -- ---------------------------------------------------------
    IF to_regclass('public.estoque_atual') IS NOT NULL
       AND to_regclass('public.movimentacoes_estoque') IS NOT NULL THEN
        WITH first_kept AS (
            SELECT DISTINCT ON (m.produto_id, m.deposito_id)
                   m.produto_id,
                   m.deposito_id,
                   m.saldo_antes
              FROM public.movimentacoes_estoque m
             WHERE COALESCE(m.data_movimentacao, m.created_at) >= v_cutoff_ts
               AND COALESCE(m.documento_referencia, '') <> 'RETENCAO_10_DIAS'
             ORDER BY
                   m.produto_id,
                   m.deposito_id,
                   COALESCE(m.data_movimentacao, m.created_at),
                   m.id
        ),
        balance_candidates AS (
            SELECT ea.produto_id,
                   ea.deposito_id,
                   COALESCE(fk.saldo_antes, ea.saldo_atual, 0) AS saldo_abertura
              FROM public.estoque_atual ea
              LEFT JOIN first_kept fk
                ON fk.produto_id = ea.produto_id
               AND fk.deposito_id = ea.deposito_id
             WHERE NOT EXISTS (
                    SELECT 1
                      FROM public.movimentacoes_estoque existing_balance
                     WHERE existing_balance.idempotency_key = format(
                           'retencao_10_dias:%s:%s:%s',
                           ea.produto_id,
                           ea.deposito_id,
                           v_cutoff_key
                     )
             )
        )
        SELECT count(*)
          INTO v_count
          FROM balance_candidates;

        IF v_execute THEN
            WITH first_kept AS (
                SELECT DISTINCT ON (m.produto_id, m.deposito_id)
                       m.produto_id,
                       m.deposito_id,
                       m.saldo_antes
                  FROM public.movimentacoes_estoque m
                 WHERE COALESCE(m.data_movimentacao, m.created_at) >= v_cutoff_ts
                   AND COALESCE(m.documento_referencia, '') <> 'RETENCAO_10_DIAS'
                 ORDER BY
                       m.produto_id,
                       m.deposito_id,
                       COALESCE(m.data_movimentacao, m.created_at),
                       m.id
            ),
            balance_candidates AS (
                SELECT ea.produto_id,
                       ea.deposito_id,
                       COALESCE(fk.saldo_antes, ea.saldo_atual, 0) AS saldo_abertura,
                       p.nome AS produto_nome
                  FROM public.estoque_atual ea
                  LEFT JOIN first_kept fk
                    ON fk.produto_id = ea.produto_id
                   AND fk.deposito_id = ea.deposito_id
                  LEFT JOIN public.produtos p
                    ON p.id = ea.produto_id
                 WHERE NOT EXISTS (
                        SELECT 1
                          FROM public.movimentacoes_estoque existing_balance
                         WHERE existing_balance.idempotency_key = format(
                               'retencao_10_dias:%s:%s:%s',
                               ea.produto_id,
                               ea.deposito_id,
                               v_cutoff_key
                         )
                 )
            )
            INSERT INTO public.movimentacoes_estoque (
                produto_id,
                deposito_id,
                tipo_movimentacao,
                quantidade,
                saldo_antes,
                saldo_depois,
                documento_referencia,
                motivo,
                data_movimentacao,
                created_at,
                produto_nome,
                idempotency_key,
                observacao
            )
            SELECT bc.produto_id,
                   bc.deposito_id,
                   'BALANCO',
                   bc.saldo_abertura,
                   0,
                   bc.saldo_abertura,
                   'RETENCAO_10_DIAS',
                   format('Retencao %s dias - saldo de abertura', v_retention_days),
                   v_cutoff_ts,
                   now()::timestamp,
                   bc.produto_nome,
                   format(
                       'retencao_10_dias:%s:%s:%s',
                       bc.produto_id,
                       bc.deposito_id,
                       v_cutoff_key
                   ),
                   format(
                       'BALANCO criado antes da limpeza de historico anterior a %s. Saldo de abertura preservado.',
                       v_cutoff::date
                   )
              FROM balance_candidates bc;
            GET DIAGNOSTICS v_count = ROW_COUNT;
        END IF;

        v_step := v_step + 1;
        INSERT INTO cleanup_old_log_records_results
        VALUES (
            v_step,
            'insert_balance',
            'movimentacoes_estoque',
            'criar BALANCO por produto/deposito antes de apagar movimentos antigos',
            v_mode,
            v_cutoff,
            v_count,
            'ok'
        );

        SELECT count(*)
          INTO v_count
          FROM public.movimentacoes_estoque child
         WHERE child.parent_movimento_id IS NOT NULL
           AND EXISTS (
                SELECT 1
                  FROM public.movimentacoes_estoque parent
                 WHERE parent.id = child.parent_movimento_id
                   AND COALESCE(parent.data_movimentacao, parent.created_at) < v_cutoff_ts
           );

        IF v_execute THEN
            UPDATE public.movimentacoes_estoque child
               SET parent_movimento_id = NULL
             WHERE child.parent_movimento_id IS NOT NULL
               AND EXISTS (
                    SELECT 1
                      FROM public.movimentacoes_estoque parent
                     WHERE parent.id = child.parent_movimento_id
                       AND COALESCE(parent.data_movimentacao, parent.created_at) < v_cutoff_ts
               );
            GET DIAGNOSTICS v_count = ROW_COUNT;
        END IF;

        v_step := v_step + 1;
        INSERT INTO cleanup_old_log_records_results
        VALUES (
            v_step,
            'update_fk',
            'movimentacoes_estoque',
            'parent_movimento_id -> NULL quando aponta para movimento antigo',
            v_mode,
            v_cutoff,
            v_count,
            'ok'
        );
    ELSE
        v_step := v_step + 1;
        INSERT INTO cleanup_old_log_records_results
        VALUES (
            v_step,
            'insert_balance',
            'movimentacoes_estoque',
            'tabela estoque_atual ou movimentacoes_estoque ausente',
            v_mode,
            v_cutoff,
            0,
            'skipped'
        );
    END IF;

    -- ---------------------------------------------------------
    -- Deletes com predicados especificos por tabela.
    -- ---------------------------------------------------------
    FOR r IN
        SELECT *
          FROM (VALUES
              ('webhook_event_attempts', 'created_at < cutoff', 'created_at < $1'),
              ('webhook_events', 'received_at < cutoff', 'received_at < $1'),
              ('task_execution_logs', 'created_at < cutoff', 'created_at < $1'),
              ('pedido_ingest_log', 'created_at < cutoff', 'created_at < $1'),
              ('grupo_mensagens_chat_shopee', 'mensagem_chat_shopee relacionada com COALESCE(created_at, created_timestamp) < cutoff', 'EXISTS (SELECT 1 FROM public.mensagem_chat_shopee m WHERE m.id = event_id AND COALESCE(m.created_at, m.created_timestamp AT TIME ZONE ''America/Sao_Paulo'') < $1::timestamp)'),
              ('mensagem_chat_shopee', 'COALESCE(created_at, created_timestamp) < cutoff', 'COALESCE(created_at, created_timestamp AT TIME ZONE ''America/Sao_Paulo'') < $1::timestamp'),
              ('system_events_log', 'created_at < cutoff', 'created_at < $1'),
              ('webhook_logs', 'created_at < cutoff', 'created_at < $1'),
              ('integration_refresh_logs', 'created_at < cutoff', 'created_at < $1'),
              ('logs_execucao_ia', 'executed_at < cutoff', 'executed_at < $1'),
              ('entity_correlation_mapping', 'created_at < cutoff', 'created_at < $1'),
              ('debug_rpc_logs', 'created_at < cutoff', 'created_at < $1'),
              ('eventos_pedido', 'created_at < cutoff', 'created_at < $1'),
              ('logs_producao_diaria', 'COALESCE(data_registro, created_at, data::timestamp) < cutoff', 'COALESCE(data_registro, created_at, data::timestamp) < $1::timestamp'),
              ('eventos_producao_v2', 'created_at < cutoff', 'created_at < $1'),
              ('eventos_producao', 'created_at < cutoff', 'created_at < $1'),
              ('demanda_estoque_processado', 'created_at < cutoff', 'created_at < $1'),
              ('snapshots_reconciliacao', 'created_at < cutoff', 'created_at < $1'),
              ('movimentacoes_estoque', 'COALESCE(data_movimentacao, created_at) < cutoff', 'COALESCE(data_movimentacao, created_at) < $1::timestamp')
          ) AS spec(table_name, rule, predicate)
    LOOP
        v_step := v_step + 1;

        IF to_regclass(format('public.%I', r.table_name)) IS NULL THEN
            INSERT INTO cleanup_old_log_records_results
            VALUES (
                v_step,
                'delete',
                r.table_name,
                r.rule,
                v_mode,
                v_cutoff,
                0,
                'skipped: table not found'
            );
            CONTINUE;
        END IF;

        EXECUTE format(
            'SELECT count(*) FROM public.%I WHERE %s',
            r.table_name,
            r.predicate
        )
        USING v_cutoff
        INTO v_count;

        IF v_execute THEN
            EXECUTE format(
                'DELETE FROM public.%I WHERE %s',
                r.table_name,
                r.predicate
            )
            USING v_cutoff;
            GET DIAGNOSTICS v_count = ROW_COUNT;
        END IF;

        INSERT INTO cleanup_old_log_records_results
        VALUES (
            v_step,
            'delete',
            r.table_name,
            r.rule,
            v_mode,
            v_cutoff,
            v_count,
            'ok'
        );
    END LOOP;
END $$;

SELECT
    step_no,
    action,
    table_name,
    rule,
    mode,
    cutoff,
    rows_affected,
    status
FROM cleanup_old_log_records_results
ORDER BY step_no;
