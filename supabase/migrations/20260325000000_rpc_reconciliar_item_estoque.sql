-- Migration: 20260325000000_rpc_reconciliar_item_estoque.sql
-- Data: 2026-03-25
-- Propósito: RPC atômica para reconciliação de estoque + tabela de snapshots
-- 
-- Esta RPC processa TODOS os movimentos de uma reconciliação em uma única
-- transação Postgres. Se qualquer movimento falhar, todo o lote é revertido.

-- ============================================================
-- 1. ADICIONAR COLUNAS FALTANTES NO LEDGER
-- ============================================================

ALTER TABLE public.demanda_estoque_processado
ADD COLUMN IF NOT EXISTS tipo_movimentacao VARCHAR(50),
ADD COLUMN IF NOT EXISTS usuario_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS produto_id INTEGER;

-- ============================================================
-- 2. TABELA DE SNAPSHOTS DE RECONCILIAÇÃO
-- ============================================================

CREATE TABLE IF NOT EXISTS public.snapshots_reconciliacao (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_demanda_id INTEGER,
    demanda_id INTEGER,
    qtd_finalizada NUMERIC(15,4),
    bom_necessario JSONB DEFAULT '[]',
    ledger_anterior JSONB DEFAULT '[]',
    deltas_calculados JSONB DEFAULT '{}',
    movimentos_gerados JSONB DEFAULT '[]',
    efetivas_calculadas JSONB DEFAULT '{}',
    correlation_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'SUCESSO',
    erro_detalhes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_item_demanda 
    ON public.snapshots_reconciliacao (item_demanda_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_correlation 
    ON public.snapshots_reconciliacao (correlation_id);

COMMENT ON TABLE public.snapshots_reconciliacao IS 
'Snapshot completo de cada reconciliação para auditoria e debug. Contém o estado completo do BOM, ledger e deltas no momento do processamento.';

-- ============================================================
-- 3. RPC ATÔMICA: reconciliar_item_estoque
-- ============================================================
-- 
-- Recebe:
--   p_item_id: ID do item de demanda
--   p_demanda_id: ID da demanda
--   p_movimentos: Array JSON de movimentos [{produto_id, deposito_id, tipo, quantidade, motivo, estagio}]
--   p_snapshot: JSON com dados de auditoria
--   p_correlation_id: ID de correlação
--   p_user_id: ID do usuário
--
-- Retorna: JSON com resultado {sucesso, movimentos_processados, snapshot_id}
--
-- GARANTIA: Se qualquer INSERT/UPDATE falhar, toda a transação é revertida (ROLLBACK).

CREATE OR REPLACE FUNCTION public.reconciliar_item_estoque(
    p_item_id INTEGER,
    p_demanda_id INTEGER,
    p_movimentos JSONB,
    p_snapshot JSONB DEFAULT '{}',
    p_correlation_id VARCHAR DEFAULT NULL,
    p_user_id VARCHAR DEFAULT NULL
) RETURNS JSONB AS $$
DECLARE
    v_mov JSONB;
    v_produto_id INTEGER;
    v_deposito_id INTEGER;
    v_tipo VARCHAR(50);
    v_quantidade NUMERIC(15,4);
    v_motivo TEXT;
    v_estagio VARCHAR(100);
    v_saldo_atual NUMERIC(15,4);
    v_saldo_novo NUMERIC(15,4);
    v_saldo_acumulado NUMERIC(15,4) := 0;
    v_snapshot_id UUID;
    v_mov_count INTEGER := 0;
    v_correlation VARCHAR(100);
    v_default_deposito_id INTEGER;
BEGIN
    -- Gerar correlation_id se não fornecido
    v_correlation := COALESCE(p_correlation_id, gen_random_uuid()::VARCHAR);
    
    -- Obter depósito padrão (id=1 = Térreo)
    SELECT id INTO v_default_deposito_id FROM public.depositos ORDER BY id LIMIT 1;
    IF v_default_deposito_id IS NULL THEN
        v_default_deposito_id := 1;
    END IF;
    
    -- Adquirir advisory lock no item para evitar concorrência (se item_id fornecido)
    IF p_item_id IS NOT NULL AND NOT pg_try_advisory_xact_lock(p_item_id) THEN
        RETURN jsonb_build_object(
            'sucesso', false,
            'erro', 'Item está sendo processado por outra transação',
            'correlation_id', v_correlation
        );
    END IF;
    
    -- Processar cada movimento atomicamente
    FOR v_mov IN SELECT * FROM jsonb_array_elements(p_movimentos)
    LOOP
        v_produto_id := (v_mov->>'produto_id')::INTEGER;
        v_deposito_id := COALESCE((v_mov->>'deposito_id')::INTEGER, v_default_deposito_id);
        v_tipo := v_mov->>'tipo';
        v_quantidade := (v_mov->>'quantidade')::NUMERIC(15,4);
        v_motivo := COALESCE(v_mov->>'motivo', '');
        v_estagio := COALESCE(v_mov->>'estagio', 'geral');
        
        -- ============================================
        -- A. Atualizar saldo em estoque_atual (FOR UPDATE = lock de linha)
        -- ============================================
        SELECT saldo_atual INTO v_saldo_atual
        FROM public.estoque_atual
        WHERE produto_id = v_produto_id AND deposito_id = v_deposito_id
        FOR UPDATE;
        
        IF v_saldo_atual IS NULL THEN
            -- Produto sem registro de estoque → criar
            v_saldo_atual := 0;
            v_saldo_novo := v_quantidade;
            INSERT INTO public.estoque_atual (produto_id, deposito_id, saldo_atual, reservado, nivel_minimo, ultima_atualizacao, created_at, updated_at)
            VALUES (v_produto_id, v_deposito_id, v_saldo_novo, 0, 0, NOW(), NOW(), NOW());
        ELSE
            v_saldo_novo := v_saldo_atual + v_quantidade;
            UPDATE public.estoque_atual 
            SET saldo_atual = v_saldo_novo, 
                ultima_atualizacao = NOW(), 
                updated_at = NOW()
            WHERE produto_id = v_produto_id AND deposito_id = v_deposito_id;
        END IF;
        
        -- ============================================
        -- B. Inserir na movimentacoes_estoque (histórico global)
        -- ============================================
        INSERT INTO public.movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            documento_referencia, correlation_id, origem_tipo, data_movimentacao, created_at
        ) VALUES (
            v_produto_id, v_deposito_id, v_tipo, v_quantidade,
            v_saldo_atual, v_saldo_novo, v_motivo, 
            CASE WHEN p_user_id ~ '^\d+$' THEN p_user_id::INTEGER ELSE NULL END,
            'DEMANDA_' || p_demanda_id, v_correlation::UUID, 
            4, -- origem_tipo 4 = RECONCILIACAO_MOTOR
            NOW(), NOW()
        );
        
        -- ============================================
        -- C. Inserir no ledger de reconciliação (demanda_estoque_processado)
        -- ============================================
        v_saldo_acumulado := v_saldo_acumulado + v_quantidade;
        
        INSERT INTO public.demanda_estoque_processado (
            item_id, demanda_id, estagio, quantidade, saldo_acumulado, 
            correlation_id, tipo_movimentacao, usuario_id, produto_id, metadata
        ) VALUES (
            p_item_id, p_demanda_id, v_estagio, v_quantidade, v_saldo_acumulado,
            v_correlation, v_tipo, p_user_id, v_produto_id, 
            jsonb_build_object('saldo_antes', v_saldo_atual, 'saldo_depois', v_saldo_novo)
        );
        
        v_mov_count := v_mov_count + 1;
    END LOOP;
    
    -- ============================================
    -- D. Salvar snapshot de reconciliação
    -- ============================================
    INSERT INTO public.snapshots_reconciliacao (
        item_demanda_id, demanda_id, qtd_finalizada,
        bom_necessario, ledger_anterior, deltas_calculados,
        movimentos_gerados, efetivas_calculadas,
        correlation_id, status
    ) VALUES (
        p_item_id, p_demanda_id,
        COALESCE((p_snapshot->>'qtd_finalizada')::NUMERIC, 0),
        COALESCE(p_snapshot->'bom_necessario', '[]'::JSONB),
        COALESCE(p_snapshot->'ledger_anterior', '[]'::JSONB),
        COALESCE(p_snapshot->'deltas_calculados', '{}'::JSONB),
        p_movimentos,
        COALESCE(p_snapshot->'efetivas_calculadas', '{}'::JSONB),
        v_correlation, 'SUCESSO'
    ) RETURNING id INTO v_snapshot_id;
    
    -- Retorno de sucesso
    RETURN jsonb_build_object(
        'sucesso', true,
        'movimentos_processados', v_mov_count,
        'snapshot_id', v_snapshot_id,
        'correlation_id', v_correlation,
        'saldo_acumulado', v_saldo_acumulado
    );
    
EXCEPTION WHEN OTHERS THEN
    -- Qualquer erro = ROLLBACK automático (transação do Postgres)
    -- Registrar snapshot de erro (em transação separada via autonomous block não disponível no PG)
    RAISE WARNING 'ERRO reconciliar_item_estoque item=%, demanda=%: % %', 
        p_item_id, p_demanda_id, SQLERRM, SQLSTATE;
    
    RETURN jsonb_build_object(
        'sucesso', false,
        'erro', SQLERRM,
        'sqlstate', SQLSTATE,
        'correlation_id', v_correlation
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION public.reconciliar_item_estoque IS 
'RPC atômica para reconciliação de estoque. Processa N movimentos em transação única.
Se qualquer movimento falhar → ROLLBACK total. Advisory lock previne concorrência.';

-- ============================================================
-- FIM DA MIGRATION
-- ============================================================
