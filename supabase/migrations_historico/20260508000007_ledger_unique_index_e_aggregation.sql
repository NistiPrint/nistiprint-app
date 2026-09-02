-- Migration: 20260508000007_ledger_unique_index_e_aggregation.sql
-- Data: 2026-05-08
-- Proposito:
--   Resolver conflito de chave unica em demanda_estoque_processado quando
--   o motor explode a BOM com producao JIT.
--
--   O motor gera, por componente da BOM:
--     - CONS_INT do estoque (qtd usada do saldo)
--     - PROD_INT JIT (qtd produzida ad-hoc)
--     - CONS_INT espelhado (consumo do JIT recem-produzido)
--   Os tres movimentos compartilham (item_id, estagio, correlation_id),
--   batendo no idx_ledger_unique_correlation criado em
--   20260324000000_motor_reconciliacao_estoque_fundacao.sql:
--     duplicate key value violates unique constraint "idx_ledger_unique_correlation"
--     Key (item_id, estagio, correlation_id)=(2, bom_137, 3ab5cc2a-...)
--
-- Mudanca:
--   1. Recriar o indice unique incluindo produto_id e tipo_movimentacao.
--      Assim cada (produto, tipo) gera 1 linha distinta no ledger.
--   2. Atualizar a RPC para gravar produto_id + tipo_movimentacao no INSERT
--      e usar ON CONFLICT DO UPDATE somando quantidades quando vierem 2
--      movimentos da mesma chave (e.g. CONS_INT estoque + CONS_INT espelhado
--      JIT do mesmo produto). A soma preserva o saldo agregado consumido
--      sem perder a distincao dos tipos entre produtos diferentes.
--
-- Rollback do indice:
--   DROP INDEX idx_ledger_unique_correlation;
--   CREATE UNIQUE INDEX idx_ledger_unique_correlation
--     ON demanda_estoque_processado(item_id, estagio, correlation_id)
--     WHERE correlation_id IS NOT NULL;

-- ============================================================
-- 1. Recriar o indice unique com produto_id + tipo_movimentacao
-- ============================================================

DROP INDEX IF EXISTS public.idx_ledger_unique_correlation;

CREATE UNIQUE INDEX idx_ledger_unique_correlation
    ON public.demanda_estoque_processado(
        item_id, estagio, correlation_id, produto_id, tipo_movimentacao
    )
    WHERE correlation_id IS NOT NULL;

COMMENT ON INDEX public.idx_ledger_unique_correlation IS
'Idempotencia do ledger: 1 linha por (item, estagio, correlation, produto, tipo). '
'A RPC reconciliar_item_estoque usa ON CONFLICT DO UPDATE para somar quantidades '
'quando movimentos da mesma chave aparecem mais de uma vez (caso da explosao JIT '
'que produz CONS_INT de estoque + CONS_INT espelhado do JIT do mesmo produto).';

-- ============================================================
-- 2. Atualizar a RPC reconciliar_item_estoque
-- ============================================================
-- Substitui a versao definida em 20260508000006_fix_reconciliar_item_estoque_demanda_id_no_ledger.sql.

CREATE OR REPLACE FUNCTION public.reconciliar_item_estoque(
    p_item_id INTEGER,
    p_demanda_id INTEGER,
    p_movimentos JSONB,
    p_snapshot JSONB,
    p_correlation_id UUID,
    p_user_id VARCHAR(255)
) RETURNS JSONB AS $$
DECLARE
    v_movimento JSONB;
    v_produto_id INTEGER;
    v_quantidade NUMERIC;
    v_tipo_movimentacao VARCHAR(50);
    v_saldo_antes NUMERIC;
    v_saldo_depois NUMERIC;
    v_mov_id INTEGER;
    v_produto_nome VARCHAR(255);
    v_demanda_nome VARCHAR(255);
    v_usuario_id INTEGER;
    v_estagio VARCHAR(50);
    v_result JSONB := '{"movimentos": [], "erros": []}'::JSONB;
BEGIN
    -- Coercao segura de p_user_id (VARCHAR) para INTEGER da FK usuarios.id.
    -- Nao-numerico ('System', 'Worker', email) -> NULL.
    IF p_user_id IS NOT NULL AND p_user_id ~ '^-?\d+$' THEN
        BEGIN
            v_usuario_id := p_user_id::INTEGER;
        EXCEPTION WHEN OTHERS THEN
            v_usuario_id := NULL;
        END;
    ELSE
        v_usuario_id := NULL;
    END IF;

    -- Buscar nome humano da demanda (campo "descricao" em demandas_producao;
    -- pode ser NULL para producao avulsa quando p_demanda_id eh NULL).
    IF p_demanda_id IS NOT NULL THEN
        SELECT descricao INTO v_demanda_nome
        FROM demandas_producao
        WHERE id = p_demanda_id;
    END IF;

    -- Processar cada movimento
    FOR v_movimento IN SELECT * FROM jsonb_array_elements(p_movimentos) LOOP
        v_produto_id := (v_movimento->>'produto_id')::INTEGER;
        v_quantidade := (v_movimento->>'quantidade')::NUMERIC;
        v_tipo_movimentacao := v_movimento->>'tipo';
        v_estagio := v_movimento->>'estagio';

        -- Buscar nome do produto (produtos.nome existe e eh NOT NULL)
        SELECT nome INTO v_produto_nome
        FROM produtos
        WHERE id = v_produto_id;

        -- Obter saldo atual (e cria registro em estoque_atual se faltar)
        SELECT saldo_atual INTO v_saldo_antes
        FROM estoque_atual
        WHERE produto_id = v_produto_id
        AND deposito_id = (v_movimento->>'deposito_id')::INTEGER
        FOR UPDATE;

        IF v_saldo_antes IS NULL THEN
            v_saldo_antes := 0;
            INSERT INTO estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
            VALUES (v_produto_id, (v_movimento->>'deposito_id')::INTEGER, v_quantidade, NOW());
            v_saldo_depois := v_quantidade;
        ELSE
            v_saldo_depois := v_saldo_antes + v_quantidade;
            UPDATE estoque_atual
            SET saldo_atual = v_saldo_depois, ultima_atualizacao = NOW(), updated_at = NOW()
            WHERE produto_id = v_produto_id
            AND deposito_id = (v_movimento->>'deposito_id')::INTEGER;
        END IF;

        -- Inserir movimentacao COM nome do produto e demanda (quando disponivel).
        -- documento_referencia preserva p_user_id em texto para auditar
        -- chamadas de 'System'/'Worker' que nao tem id numerico em usuarios.
        INSERT INTO movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            documento_referencia, correlation_id, origem_tipo, data_movimentacao,
            item_demanda_id, produto_nome, demanda_nome
        ) VALUES (
            v_produto_id, (v_movimento->>'deposito_id')::INTEGER, v_tipo_movimentacao, v_quantidade,
            v_saldo_antes, v_saldo_depois, v_movimento->>'motivo', v_usuario_id,
            CASE WHEN v_usuario_id IS NULL THEN 'caller=' || COALESCE(p_user_id, 'NULL') ELSE NULL END,
            p_correlation_id, NULL, NOW(),
            p_item_id, v_produto_nome, v_demanda_nome
        ) RETURNING id INTO v_mov_id;

        -- Inserir/atualizar no ledger de demanda (apenas se associado a demanda).
        -- Inclui produto_id e tipo_movimentacao para o indice unique novo.
        -- Em conflito (e.g. CONS_INT estoque + CONS_INT espelhado JIT do mesmo
        -- produto no mesmo estagio), soma quantidades em vez de explodir.
        IF p_item_id IS NOT NULL AND p_demanda_id IS NOT NULL THEN
            INSERT INTO demanda_estoque_processado (
                item_id, demanda_id, estagio, quantidade, correlation_id,
                saldo_acumulado, produto_id, tipo_movimentacao, created_at
            ) VALUES (
                p_item_id, p_demanda_id, v_estagio, v_quantidade,
                p_correlation_id, v_saldo_depois, v_produto_id, v_tipo_movimentacao, NOW()
            )
            ON CONFLICT (item_id, estagio, correlation_id, produto_id, tipo_movimentacao)
                WHERE correlation_id IS NOT NULL
            DO UPDATE SET
                quantidade      = demanda_estoque_processado.quantidade + EXCLUDED.quantidade,
                saldo_acumulado = EXCLUDED.saldo_acumulado,
                updated_at      = NOW();
        END IF;

        v_result := v_result || jsonb_build_object(
            'movimento_id', v_mov_id,
            'produto_id', v_produto_id,
            'quantidade', v_quantidade
        );
    END LOOP;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION public.reconciliar_item_estoque(INTEGER, INTEGER, JSONB, JSONB, UUID, VARCHAR) IS
'RPC atomica do motor de reconciliacao de estoque. Aplica movimentos, '
'atualiza saldos e registra ledger demanda_estoque_processado. '
'Usa ON CONFLICT DO UPDATE para somar quantidades quando ha duplicidade '
'na chave (item, estagio, correlation, produto, tipo) — caso da explosao '
'JIT em que CONS_INT estoque e CONS_INT espelhado convergem na mesma chave.';
