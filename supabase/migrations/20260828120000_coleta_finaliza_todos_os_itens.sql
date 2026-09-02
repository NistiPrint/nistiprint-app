-- Coleta total finaliza TODOS os itens da demanda.
--
-- Antes, o unico loop da funcao fazia duas coisas ao mesmo tempo: finalizar o
-- item e dar baixa no estoque. Como ele filtrava por `produto_id IS NOT NULL`
-- (e ainda fazia JOIN em produtos), item sem produto mapeado nunca era
-- finalizado. Na demanda 139, 20 de 21 itens ficaram 'Pendente' com
-- finalizados_qtd = 0 depois de a demanda ir para COLETADO.
--
-- Agora sao dois passos distintos:
--   1. Finalizacao: todos os itens da demanda, sem filtro. E um fato
--      operacional — a mercadoria saiu, o item acabou.
--   2. Baixa de estoque: so os itens com produto mapeado. Item sem produto
--      nao tem o que movimentar.
--
-- A funcao tambem passa a devolver `itens_finalizados` para que o chamador
-- consiga enxergar a diferenca entre o que foi finalizado e o que foi baixado.
--
-- Esta funcao ja existia no banco de producao sem migration correspondente.
-- Este arquivo passa a ser a fonte da verdade dela.

CREATE OR REPLACE FUNCTION public.registrar_saida_coleta_demanda(
    p_demanda_id integer,
    p_user_id text DEFAULT 'System'::text
)
RETURNS jsonb
LANGUAGE plpgsql
AS $function$
DECLARE
    v_status       text;
    v_deposito     int;
    v_correlation  uuid := gen_random_uuid();
    v_usuario_id   int;
    v_ja           int;
    v_item         record;
    v_saldo_antes  numeric;
    v_saldo_depois numeric;
    v_linhas       int := 0;
    v_total        numeric := 0;
    v_finalizados  int := 0;
    v_ids_a_reconciliar int[];
    v_sem_produto  int := 0;
BEGIN
    SELECT status INTO v_status FROM public.demandas_producao WHERE id = p_demanda_id;
    IF v_status IS NULL THEN
        RETURN jsonb_build_object('ok', false, 'motivo', 'demanda_inexistente');
    END IF;

    IF v_status <> 'COLETADO' THEN
        RETURN jsonb_build_object('ok', false, 'motivo', 'demanda_nao_coletada', 'status', v_status);
    END IF;

    -- ------------------------------------------------------------------
    -- PASSO 1: finalizar TODOS os itens, com ou sem produto mapeado.
    -- ------------------------------------------------------------------
    -- Quem ainda precisa passar pelo motor: item com producao em atraso E com
    -- produto mapeado. Capturado ANTES do UPDATE, porque depois dele todo mundo
    -- fica com finalizados_qtd = quantidade e a informacao se perde.
    SELECT COALESCE(array_agg(id), ARRAY[]::int[]) INTO v_ids_a_reconciliar
      FROM public.itens_demanda
     WHERE demanda_id = p_demanda_id
       AND COALESCE(quantidade, 0) > 0
       AND COALESCE(finalizados_qtd, 0) < COALESCE(quantidade, 0)
       AND produto_id IS NOT NULL;

    -- A finalizacao alcanca tambem o item cuja quantidade ja batia mas que
    -- ficou com status_item errado (visto na demanda 139: finalizados_qtd = 3
    -- de 3 e status_item ainda 'Em Andamento').
    WITH finalizados AS (
        UPDATE public.itens_demanda
           SET finalizados_qtd = COALESCE(quantidade, 0),
               status_item     = 'Concluído',
               updated_at      = now()
         WHERE demanda_id = p_demanda_id
           AND COALESCE(quantidade, 0) > 0
           AND (
                COALESCE(finalizados_qtd, 0) < COALESCE(quantidade, 0)
                OR status_item IS DISTINCT FROM 'Concluído'
               )
        RETURNING id
    )
    SELECT count(*) INTO v_finalizados FROM finalizados;

    -- Item sem produto nao entra na fila: nao ha o que reconciliar, e enfileirar
    -- so geraria ruido no consolidador. Item ja reconciliado antes tambem fica
    -- de fora — seu delta seria zero.
    IF COALESCE(array_length(v_ids_a_reconciliar, 1), 0) > 0 THEN
        UPDATE public.itens_demanda
           SET status_processamento = 'PENDENTE'
         WHERE id = ANY(v_ids_a_reconciliar);

        INSERT INTO public.eventos_producao_v2 (
            item_demanda_id, demanda_id, estagio, quantidade_reportada,
            tipo_evento, processado, correlation_id, created_at
        )
        SELECT i.id, p_demanda_id, 'finalizados_qtd', COALESCE(i.quantidade, 0),
               'LIQUIDACAO', false, v_correlation, now()
          FROM public.itens_demanda i
         WHERE i.id = ANY(v_ids_a_reconciliar);
    END IF;

    -- ------------------------------------------------------------------
    -- PASSO 2: baixa de estoque, somente para itens com produto mapeado.
    -- ------------------------------------------------------------------
    SELECT count(*) INTO v_ja
      FROM public.movimentacoes_estoque m
      JOIN public.itens_demanda i ON i.id = m.item_demanda_id
     WHERE i.demanda_id = p_demanda_id AND m.tipo_movimentacao = 'SAIDA_COLETA';

    SELECT count(*) INTO v_sem_produto
      FROM public.itens_demanda
     WHERE demanda_id = p_demanda_id AND produto_id IS NULL;

    IF v_ja > 0 THEN
        -- Baixa ja registrada numa passagem anterior. A finalizacao do passo 1
        -- e idempotente e pode ter corrigido itens que ficaram para tras, entao
        -- ainda assim reportamos o que foi feito agora.
        RETURN jsonb_build_object(
            'ok', true,
            'motivo', 'ja_registrada',
            'demanda_id', p_demanda_id,
            'movimentos_existentes', v_ja,
            'itens_finalizados', v_finalizados,
            'itens_sem_produto_mapeado', v_sem_produto
        );
    END IF;

    SELECT COALESCE((SELECT (valor #>> '{}')::int FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_default_production_deposit_id'),
                    (SELECT id FROM public.depositos ORDER BY id LIMIT 1), 1)
      INTO v_deposito;

    v_usuario_id := CASE WHEN p_user_id ~ '^-?\d+$' THEN p_user_id::int ELSE NULL END;

    FOR v_item IN
        SELECT i.id AS item_id, i.produto_id, p.nome AS produto_nome,
               COALESCE(i.quantidade, 0)::numeric AS qtd_demandada
          FROM public.itens_demanda i
          JOIN public.produtos p ON p.id = i.produto_id
         WHERE i.demanda_id = p_demanda_id
           AND i.produto_id IS NOT NULL
           AND COALESCE(i.quantidade, 0) > 0
    LOOP
        -- Saida do demandado, nao do que a tela registrou.
        SELECT saldo_atual INTO v_saldo_antes
          FROM public.estoque_atual
         WHERE produto_id = v_item.produto_id AND deposito_id = v_deposito
         FOR UPDATE;

        IF v_saldo_antes IS NULL THEN
            v_saldo_antes := 0;
            INSERT INTO public.estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
            VALUES (v_item.produto_id, v_deposito, -v_item.qtd_demandada, now());
            v_saldo_depois := -v_item.qtd_demandada;
        ELSE
            v_saldo_depois := v_saldo_antes - v_item.qtd_demandada;
            UPDATE public.estoque_atual
               SET saldo_atual = v_saldo_depois, ultima_atualizacao = now(), updated_at = now()
             WHERE produto_id = v_item.produto_id AND deposito_id = v_deposito;
        END IF;

        INSERT INTO public.movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, usuario_id,
            correlation_id, data_movimentacao, item_demanda_id, produto_nome, estagio
        ) VALUES (
            v_item.produto_id, v_deposito, 'SAIDA_COLETA', -v_item.qtd_demandada,
            v_saldo_antes, v_saldo_depois,
            'Saída por coleta completa da demanda ' || p_demanda_id, v_usuario_id,
            v_correlation, now(), v_item.item_id, v_item.produto_nome, 'coleta'
        );

        INSERT INTO public.demanda_estoque_processado (
            item_id, demanda_id, estagio, quantidade, correlation_id,
            saldo_acumulado, produto_id, tipo_movimentacao, created_at
        ) VALUES (
            v_item.item_id, p_demanda_id, 'coleta', -v_item.qtd_demandada, v_correlation,
            v_saldo_depois, v_item.produto_id, 'SAIDA_COLETA', now()
        )
        ON CONFLICT (item_id, estagio, correlation_id, produto_id, tipo_movimentacao)
            WHERE correlation_id IS NOT NULL
        DO NOTHING;

        v_linhas := v_linhas + 1;
        v_total  := v_total + v_item.qtd_demandada;
    END LOOP;

    RETURN jsonb_build_object(
        'ok', true,
        'demanda_id', p_demanda_id,
        'correlation_id', v_correlation,
        'itens_finalizados', v_finalizados,
        'itens_baixados', v_linhas,
        'quantidade_total', v_total,
        'itens_sem_produto_mapeado', v_sem_produto
    );
END; $function$;
