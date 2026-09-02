-- Migration: rpc_reconciliar_estoque_v2
-- Data: 2026-05-08
-- Propósito: RPC atômica para o Motor de Estoque v2

CREATE OR REPLACE FUNCTION public.reconciliar_estoque_v2(
    p_item_id INTEGER,
    p_movimentos JSONB,
    p_estado_novo JSONB,
    p_snapshot JSONB,
    p_lote_id UUID,
    p_user_id VARCHAR DEFAULT NULL
) RETURNS JSONB AS $$
DECLARE
    v_mov JSONB;
    v_produto_id INTEGER;
    v_deposito_id INTEGER;
    v_tipo VARCHAR(50);
    v_quantidade NUMERIC(15,4);
    v_is_jit BOOLEAN;
    v_coluna_origem VARCHAR(50);
    v_motivo TEXT;
    
    v_saldo_atual NUMERIC(15,4);
    v_saldo_novo NUMERIC(15,4);
    v_mov_id INTEGER;
    v_snapshot_id UUID;
    v_mov_count INTEGER := 0;
    v_default_deposito_id INTEGER;
    
    v_user_id_int INTEGER;
BEGIN
    -- 1. Resolver usuário
    IF p_user_id ~ '^\d+$' THEN
        v_user_id_int := p_user_id::INTEGER;
    END IF;

    -- 2. Obter depósito padrão
    SELECT id INTO v_default_deposito_id FROM public.depositos ORDER BY id LIMIT 1;
    IF v_default_deposito_id IS NULL THEN v_default_deposito_id := 1; END IF;

    -- 3. Lock pessimista no item (Advisory Lock na transação)
    IF NOT pg_try_advisory_xact_lock(p_item_id) THEN
        RETURN jsonb_build_object(
            'sucesso', false,
            'erro', 'Item está sendo processado por outra transação (Lock ID: ' || p_item_id || ')'
        );
    END IF;

    -- 4. Atualizar o estado do item_demanda
    UPDATE public.itens_demanda
    SET 
        capas_impressas_qtd = (p_estado_novo->>'capas_impressas_qtd')::NUMERIC,
        capas_produzidas_qtd = (p_estado_novo->>'capas_produzidas_qtd')::NUMERIC,
        capas_prontas_retirada_qtd = (p_estado_novo->>'capas_prontas_retirada_qtd')::NUMERIC,
        miolos_prontos_retirada_qtd = (p_estado_novo->>'miolos_prontos_retirada_qtd')::NUMERIC,
        expedicao_capas_retiradas_qtd = (p_estado_novo->>'expedicao_capas_retiradas_qtd')::NUMERIC,
        expedicao_miolos_retirados_qtd = (p_estado_novo->>'expedicao_miolos_retirados_qtd')::NUMERIC,
        finalizados_qtd = (p_estado_novo->>'finalizados_qtd')::NUMERIC,
        updated_at = NOW()
    WHERE id = p_item_id;

    -- 5. Processar Movimentos
    FOR v_mov IN SELECT * FROM jsonb_array_elements(p_movimentos)
    LOOP
        v_produto_id := (v_mov->>'produto_id')::INTEGER;
        v_tipo := v_mov->>'tipo';
        v_quantidade := (v_mov->>'quantidade')::NUMERIC(15,4);
        v_is_jit := COALESCE((v_mov->>'is_jit')::BOOLEAN, FALSE);
        v_coluna_origem := v_mov->>'coluna_origem';
        v_motivo := v_mov->>'motivo';
        
        -- Lock advisório por produto (evita race condition no saldo_global)
        -- Usamos lock de 64 bits combinando um prefixo e o ID do produto
        PERFORM pg_advisory_xact_lock(hash_any(v_produto_id::text));

        -- A. Atualizar Saldo
        SELECT saldo_atual INTO v_saldo_atual
        FROM public.estoque_atual
        WHERE produto_id = v_produto_id AND deposito_id = v_default_deposito_id
        FOR UPDATE;

        IF v_saldo_atual IS NULL THEN
            v_saldo_atual := 0;
            v_saldo_novo := v_quantidade;
            INSERT INTO public.estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
            VALUES (v_produto_id, v_default_deposito_id, v_saldo_novo, NOW());
        ELSE
            v_saldo_novo := v_saldo_atual + v_quantidade;
            UPDATE public.estoque_atual 
            SET saldo_atual = v_saldo_novo, ultima_atualizacao = NOW(), updated_at = NOW()
            WHERE produto_id = v_produto_id AND deposito_id = v_default_deposito_id;
        END IF;

        -- B. Inserir no histórico (movimentacoes_estoque) com os novos campos v2
        INSERT INTO public.movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            lote_id, is_jit, coluna_origem, item_demanda_id,
            data_movimentacao, created_at
        ) VALUES (
            v_produto_id, v_default_deposito_id, v_tipo, v_quantidade,
            v_saldo_atual, v_saldo_novo, v_motivo, v_user_id_int,
            p_lote_id, v_is_jit, v_coluna_origem, p_item_id,
            NOW(), NOW()
        ) RETURNING id INTO v_mov_id;

        v_mov_count := v_mov_count + 1;
    END LOOP;

    -- 6. Registrar Snapshot (Auditoria v2)
    INSERT INTO public.snapshots_reconciliacao (
        item_demanda_id, 
        demanda_id,
        qtd_finalizada,
        deltas_calculados,
        efetivas_calculadas,
        correlation_id,
        metadata,
        status
    ) VALUES (
        p_item_id,
        (SELECT demanda_id FROM public.itens_demanda WHERE id = p_item_id),
        (p_estado_novo->>'finalizados_qtd')::NUMERIC,
        p_snapshot->'deltas_calculados',
        p_snapshot->'efetivas_calculadas',
        p_lote_id::VARCHAR,
        p_snapshot,
        'SUCESSO'
    ) RETURNING id INTO v_snapshot_id;

    RETURN jsonb_build_object(
        'sucesso', true,
        'movimentos_processados', v_mov_count,
        'lote_id', p_lote_id,
        'snapshot_id', v_snapshot_id
    );

EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'ERRO em reconciliar_estoque_v2: % (%)', SQLERRM, SQLSTATE;
    RETURN jsonb_build_object(
        'sucesso', false,
        'erro', SQLERRM,
        'sqlstate', SQLSTATE
    );
END;
$$ LANGUAGE plpgsql;
