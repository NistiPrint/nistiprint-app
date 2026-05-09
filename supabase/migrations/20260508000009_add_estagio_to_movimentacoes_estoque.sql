-- Migration: 20260508000009_add_estagio_to_movimentacoes_estoque.sql
-- Data: 2026-05-08
-- Proposito:
--   Adicionar coluna "estagio" em movimentacoes_estoque para que o agrupamento
--   da view de movimentacoes consolidadas (Opcao B) possa separar:
--     - Estagio "finalizados_qtd" (PROD_ACAB do produto principal + componentes diretos)
--     - Estagio "bom_<produto_id>" (cada producao JIT recursiva tem seu proprio bloco)
--
--   Hoje so existe correlation_id; movimentos da mesma reconciliacao mas de
--   sub-arvores BOM diferentes ficam misturados na UI.
--
-- Mudancas:
--   1. ALTER TABLE: adicionar coluna estagio VARCHAR(50) nullable.
--   2. Index para consulta agrupada (correlation_id, estagio).
--   3. Atualizar RPC reconciliar_item_estoque para gravar v_estagio.
--   4. Backfill: copia estagio do ledger demanda_estoque_processado para
--      movimentacoes existentes via correlation_id+item+produto+tipo.

-- ============================================================
-- 1. Adicionar coluna estagio
-- ============================================================

ALTER TABLE public.movimentacoes_estoque
  ADD COLUMN IF NOT EXISTS estagio VARCHAR(50);

COMMENT ON COLUMN public.movimentacoes_estoque.estagio IS
'Estagio da reconciliacao que originou o movimento (ex: finalizados_qtd, bom_137). '
'Usado pelo agrupamento da view view_movimentacoes_consolidadas para distinguir '
'sub-arvores BOM dentro do mesmo correlation_id.';

CREATE INDEX IF NOT EXISTS idx_movimentacoes_estoque_correlation_estagio
  ON public.movimentacoes_estoque (correlation_id, estagio)
  WHERE correlation_id IS NOT NULL;

-- ============================================================
-- 2. Limpeza de trigger legado bugado em movimentacoes_estoque
-- ============================================================
-- O initial_schema.sql linha 3464 anexou o trigger generico
-- update_updated_at_column() em movimentacoes_estoque, mas a tabela
-- nao tem coluna updated_at. Qualquer UPDATE na tabela hoje explode
-- com "record 'new' has no field 'updated_at'". O trigger eh inutil —
-- vamos drop antes de qualquer UPDATE (incluindo nosso backfill).

DROP TRIGGER IF EXISTS update_movimentacoes_estoque_updated_at
  ON public.movimentacoes_estoque;

-- ============================================================
-- 3. Backfill: copiar estagio do ledger
-- ============================================================
-- demanda_estoque_processado ja grava estagio, podemos usar como fonte
-- de verdade para preencher movimentos historicos. correlation_id em
-- movimentacoes_estoque eh UUID; em demanda_estoque_processado eh VARCHAR(100).
-- Cast seguro para text dos dois lados.

DO $$
DECLARE
  v_atualizadas INTEGER;
BEGIN
  WITH update_estagio AS (
    UPDATE public.movimentacoes_estoque m
       SET estagio = d.estagio
      FROM public.demanda_estoque_processado d
     WHERE m.estagio IS NULL
       AND m.correlation_id IS NOT NULL
       AND m.correlation_id::text = d.correlation_id::text
       AND m.item_demanda_id = d.item_id
       AND m.produto_id = d.produto_id
       AND m.tipo_movimentacao = d.tipo_movimentacao
    RETURNING m.id
  )
  SELECT COUNT(*) INTO v_atualizadas FROM update_estagio;

  RAISE NOTICE 'Backfill estagio em movimentacoes_estoque: % linhas atualizadas.', v_atualizadas;
END $$;

-- ============================================================
-- 3. Atualizar RPC reconciliar_item_estoque para gravar estagio
-- ============================================================
-- Substitui a versao definida em
-- 20260508000008_fix_reconciliar_item_estoque_response_envelope.sql.

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
    IF p_user_id IS NOT NULL AND p_user_id ~ '^-?\d+$' THEN
        BEGIN
            v_usuario_id := p_user_id::INTEGER;
        EXCEPTION WHEN OTHERS THEN
            v_usuario_id := NULL;
        END;
    ELSE
        v_usuario_id := NULL;
    END IF;

    -- Buscar nome humano da demanda
    IF p_demanda_id IS NOT NULL THEN
        SELECT descricao INTO v_demanda_nome
          FROM demandas_producao
         WHERE id = p_demanda_id;
    END IF;

    FOR v_movimento IN SELECT * FROM jsonb_array_elements(p_movimentos) LOOP
        v_produto_id := (v_movimento->>'produto_id')::INTEGER;
        v_quantidade := (v_movimento->>'quantidade')::NUMERIC;
        v_tipo_movimentacao := v_movimento->>'tipo';
        v_estagio := v_movimento->>'estagio';

        SELECT nome INTO v_produto_nome
          FROM produtos
         WHERE id = v_produto_id;

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

        -- INSERT em movimentacoes_estoque agora inclui estagio.
        INSERT INTO movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            documento_referencia, correlation_id, origem_tipo, data_movimentacao,
            item_demanda_id, produto_nome, demanda_nome, estagio
        ) VALUES (
            v_produto_id, (v_movimento->>'deposito_id')::INTEGER, v_tipo_movimentacao, v_quantidade,
            v_saldo_antes, v_saldo_depois, v_movimento->>'motivo', v_usuario_id,
            CASE WHEN v_usuario_id IS NULL THEN 'caller=' || COALESCE(p_user_id, 'NULL') ELSE NULL END,
            p_correlation_id, NULL, NOW(),
            p_item_id, v_produto_nome, v_demanda_nome, v_estagio
        ) RETURNING id INTO v_mov_id;

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
'RPC atomica do motor de reconciliacao. Grava estagio em movimentacoes_estoque '
'para permitir agrupamento por sub-arvore BOM na view view_movimentacoes_consolidadas.';
