-- Migration: 20260508000006_fix_reconciliar_item_estoque_demanda_id_no_ledger.sql
-- Data: 2026-05-08
-- Proposito:
--   A RPC public.reconciliar_item_estoque inseria em demanda_estoque_processado
--   sem fornecer demanda_id, mas a coluna eh INTEGER NOT NULL (FK p/
--   demandas_producao.id). Resultado:
--     null value in column "demanda_id" of relation "demanda_estoque_processado"
--     violates not-null constraint (code 23502).
--
-- Mudanca:
--   - Incluir demanda_id (= p_demanda_id) no INSERT do ledger.
--   - Manter a logica anterior (cast seguro de p_user_id, descricao da demanda).
--
-- Substitui a versao definida em 20260508000005_fix_reconciliar_item_estoque_user_id_cast.sql.

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

        -- Buscar nome do produto (produtos.nome existe e eh NOT NULL)
        SELECT nome INTO v_produto_nome
        FROM produtos
        WHERE id = v_produto_id;

        -- Obter saldo atual
        SELECT saldo_atual INTO v_saldo_antes
        FROM estoque_atual
        WHERE produto_id = v_produto_id
        AND deposito_id = (v_movimento->>'deposito_id')::INTEGER
        FOR UPDATE;

        IF v_saldo_antes IS NULL THEN
            v_saldo_antes := 0;
            INSERT INTO estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
            VALUES (v_produto_id, (v_movimento->>'deposito_id')::INTEGER, v_quantidade, NOW());
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

        -- Inserir no ledger de demanda (apenas se associado a demanda).
        -- IMPORTANTE: demanda_id eh INTEGER NOT NULL — a versao anterior
        -- omitia a coluna e o INSERT explodia com codigo 23502.
        IF p_item_id IS NOT NULL AND p_demanda_id IS NOT NULL THEN
            INSERT INTO demanda_estoque_processado (
                item_id, demanda_id, estagio, quantidade, correlation_id,
                saldo_acumulado, created_at
            ) VALUES (
                p_item_id, p_demanda_id, v_movimento->>'estagio', v_quantidade,
                p_correlation_id, v_saldo_depois, NOW()
            );
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
'atualiza saldos e registra ledger demanda_estoque_processado (demanda_id NOT NULL). '
'p_user_id eh aceito como VARCHAR e convertido para INTEGER quando numerico; '
'valores nao-numericos gravam NULL em usuario_id e ficam preservados em documento_referencia.';
