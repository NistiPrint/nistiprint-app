-- Atualizar RPC para incluir nome do produto e demanda quando disponível
-- Isso permite rastreamento de movimentações por "produto X da demanda Y"
-- As colunas podem ser NULL quando não associadas a uma demanda (produção avulsa)

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
    v_result JSONB := '{"movimentos": [], "erros": []}'::JSONB;
BEGIN
    -- Buscar nome da demanda (pode ser NULL para produção avulsa)
    IF p_demanda_id IS NOT NULL THEN
        SELECT nome INTO v_demanda_nome
        FROM demandas_producao
        WHERE id = p_demanda_id;
    END IF;
    
    -- Processar cada movimento
    FOR v_movimento IN SELECT * FROM jsonb_array_elements(p_movimentos) LOOP
        v_produto_id := (v_movimento->>'produto_id')::INTEGER;
        v_quantidade := (v_movimento->>'quantidade')::NUMERIC;
        v_tipo_movimentacao := v_movimento->>'tipo';
        
        -- Buscar nome do produto
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
        
        -- Inserir movimentação COM nome do produto e demanda (quando disponível)
        INSERT INTO movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            documento_referencia, correlation_id, origem_tipo, data_movimentacao,
            item_demanda_id, produto_nome, demanda_nome
        ) VALUES (
            v_produto_id, (v_movimento->>'deposito_id')::INTEGER, v_tipo_movimentacao, v_quantidade,
            v_saldo_antes, v_saldo_depois, v_movimento->>'motivo', p_user_id,
            NULL, p_correlation_id, NULL, NOW(),
            p_item_id, v_produto_nome, v_demanda_nome
        ) RETURNING id INTO v_mov_id;
        
        -- Inserir no ledger de demanda (apenas se associado a demanda)
        IF p_item_id IS NOT NULL THEN
            INSERT INTO demanda_estoque_processado (
                item_id, estagio, quantidade, correlation_id,
                saldo_acumulado, created_at
            ) VALUES (
                p_item_id, v_movimento->>'estagio', v_quantidade, p_correlation_id,
                v_saldo_depois, NOW()
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
