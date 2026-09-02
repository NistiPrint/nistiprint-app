-- Migration: 20260508000008_fix_reconciliar_item_estoque_response_envelope.sql
-- Data: 2026-05-08
-- Proposito:
--   A RPC public.reconciliar_item_estoque retornava JSONB sem o campo
--   "sucesso", mas o motor (motor_reconciliacao_estoque._persistir_transacional)
--   verifica:
--     if not response.data or not response.data.get('sucesso'):
--         raise Exception(f"Falha na RPC de reconciliacao: ...")
--
--   Resultado: a RPC executava com sucesso (HTTP 200, INSERTs commitados),
--   mas o motor levantava "Falha na RPC de reconciliacao: None" porque
--   .get('sucesso') retornava None.
--
-- Mudanca:
--   1. Garantir que a RPC retorne sempre {"sucesso": true, ...} no caminho feliz.
--   2. Acumular corretamente os movimentos no array "movimentos" (antes a
--      operacao "||" entre objetos JSONB sobrescrevia campos a cada iteracao,
--      perdendo o histograma de movimentos).
--   3. Adicionar bloco EXCEPTION que captura erros e retorna
--      {"sucesso": false, "erro": "..."} para que o motor possa logar
--      a mensagem real em vez de "None".
--
-- Substitui a versao definida em 20260508000007_ledger_unique_index_e_aggregation.sql.

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
    v_movimentos_resp JSONB := '[]'::JSONB;
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

        -- Acumular o movimento no array de resposta (em vez de sobrescrever
        -- como a versao anterior fazia com "||" sobre o objeto raiz).
        v_movimentos_resp := v_movimentos_resp || jsonb_build_array(jsonb_build_object(
            'movimento_id', v_mov_id,
            'produto_id', v_produto_id,
            'quantidade', v_quantidade,
            'tipo', v_tipo_movimentacao,
            'estagio', v_estagio
        ));
    END LOOP;

    RETURN jsonb_build_object(
        'sucesso', true,
        'movimentos', v_movimentos_resp,
        'erros', '[]'::JSONB,
        'snapshot_id', NULL,
        'item_id', p_item_id,
        'demanda_id', p_demanda_id,
        'correlation_id', p_correlation_id
    );

EXCEPTION
    WHEN OTHERS THEN
        -- Captura qualquer erro durante a execucao e retorna envelope
        -- {sucesso: false, erro: <SQLERRM>} para que o caller (motor)
        -- possa logar a mensagem real ao inves de "None".
        -- A transacao eh revertida automaticamente pelo PostgreSQL.
        RETURN jsonb_build_object(
            'sucesso', false,
            'erro', SQLERRM,
            'sqlstate', SQLSTATE,
            'item_id', p_item_id,
            'demanda_id', p_demanda_id,
            'correlation_id', p_correlation_id
        );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION public.reconciliar_item_estoque(INTEGER, INTEGER, JSONB, JSONB, UUID, VARCHAR) IS
'RPC atomica do motor de reconciliacao de estoque. Retorna sempre envelope '
'{sucesso: bool, ...} esperado pelo caller. Em caminho feliz: '
'{sucesso: true, movimentos: [...], erros: [], ...}. '
'Em erro: {sucesso: false, erro: SQLERRM, sqlstate: SQLSTATE, ...} (transacao revertida).';
