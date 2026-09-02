-- Cancelar e a acao padrao; deletar e a excecao.
--
-- ## Por que cancelar em vez de deletar
--
-- Um lote que ja produziu ou ja deu baixa deixou rastro em movimentacoes_estoque
-- e demanda_estoque_processado — ambos com FK ON DELETE NO ACTION. O DELETE nem
-- chega a acontecer: o banco recusa. Pior, o codigo antigo engolia a excecao e a
-- API respondia "deletada com sucesso" para uma demanda que continuava viva.
--
-- E mesmo se o DELETE passasse ele estaria errado: apagaria o ledger de uma
-- coleta que existiu. Estoque se desfaz com movimento compensatorio, nunca
-- apagando a linha original.
--
-- O vinculo em demandas_pedidos e mantido: `pedido_tem_demanda`,
-- `get_demandas_do_pedido` e a torre ja ignoram demanda CANCELADO, entao o
-- pedido volta a ser trabalho pendente sem perder o historico de que um dia
-- esteve neste lote. O carimbo `despachado_em` cai sozinho, pelo trigger de
-- 20260828120007_despachado_em_derivado_por_trigger.sql.

CREATE OR REPLACE FUNCTION public.despacho_cancelar_demanda(
    p_demanda_id integer,
    p_motivo     text DEFAULT NULL,
    p_user_id    text DEFAULT 'System'
)
RETURNS TABLE (
    out_demanda_codigo    text,
    out_pedidos_devolvidos integer,
    out_estornos_estoque   integer
)
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_status  text;
    v_codigo  text;
    v_corr    uuid := gen_random_uuid();
    v_mov     record;
    v_antes   numeric;
    v_depois  numeric;
    v_estornos integer := 0;
    v_pedidos  integer := 0;
BEGIN
    SELECT d.status, d.demanda_id INTO v_status, v_codigo
      FROM public.demandas_producao d WHERE d.id = p_demanda_id FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Demanda % nao encontrada', p_demanda_id USING ERRCODE = 'no_data_found';
    END IF;

    IF v_status IN ('CANCELADO', 'Cancelado') THEN
        RAISE EXCEPTION 'Demanda % ja esta cancelada', v_codigo USING ERRCODE = 'invalid_parameter_value';
    END IF;

    -- Estorno das saidas de coleta. Producao (CONS_MP, PROD_INT, PROD_ACAB) NAO
    -- e estornada: o material foi consumido de verdade e o acabado existe na
    -- prateleira. So a saida — a mercadoria que nao saiu — volta.
    FOR v_mov IN
        SELECT m.id, m.produto_id, m.deposito_id, m.quantidade, m.item_demanda_id, m.produto_nome
          FROM public.movimentacoes_estoque m
          JOIN public.itens_demanda i ON i.id = m.item_demanda_id
         WHERE i.demanda_id = p_demanda_id
           AND m.tipo_movimentacao = 'SAIDA_COLETA'
           AND NOT EXISTS (
                 SELECT 1 FROM public.movimentacoes_estoque e
                  WHERE e.item_demanda_id = m.item_demanda_id
                    AND e.estagio = 'estorno_coleta'
                    AND e.produto_id = m.produto_id)
    LOOP
        SELECT saldo_atual INTO v_antes
          FROM public.estoque_atual
         WHERE produto_id = v_mov.produto_id AND deposito_id = v_mov.deposito_id
         FOR UPDATE;
        v_antes  := COALESCE(v_antes, 0);
        v_depois := v_antes - v_mov.quantidade;  -- quantidade da saida e negativa

        IF EXISTS (SELECT 1 FROM public.estoque_atual
                    WHERE produto_id = v_mov.produto_id AND deposito_id = v_mov.deposito_id) THEN
            UPDATE public.estoque_atual
               SET saldo_atual = v_depois, ultima_atualizacao = now(), updated_at = now()
             WHERE produto_id = v_mov.produto_id AND deposito_id = v_mov.deposito_id;
        ELSE
            INSERT INTO public.estoque_atual (produto_id, deposito_id, saldo_atual, ultima_atualizacao)
            VALUES (v_mov.produto_id, v_mov.deposito_id, v_depois, now());
        END IF;

        INSERT INTO public.movimentacoes_estoque (
            produto_id, deposito_id, tipo_movimentacao, quantidade,
            saldo_antes, saldo_depois, motivo, correlation_id,
            data_movimentacao, item_demanda_id, produto_nome, estagio
        ) VALUES (
            v_mov.produto_id, v_mov.deposito_id, 'ESTORNO', -v_mov.quantidade,
            v_antes, v_depois,
            'Estorno da coleta: demanda cancelada (mov. origem ' || v_mov.id || ')',
            v_corr, now(), v_mov.item_demanda_id, v_mov.produto_nome, 'estorno_coleta'
        );

        INSERT INTO public.demanda_estoque_processado (
            item_id, demanda_id, estagio, quantidade, correlation_id,
            saldo_acumulado, produto_id, tipo_movimentacao, created_at
        ) VALUES (
            v_mov.item_demanda_id, p_demanda_id, 'estorno_coleta', -v_mov.quantidade, v_corr,
            v_depois, v_mov.produto_id, 'ESTORNO', now()
        )
        ON CONFLICT DO NOTHING;

        v_estornos := v_estornos + 1;
    END LOOP;

    SELECT count(*) INTO v_pedidos
      FROM public.demandas_pedidos WHERE demanda_id = p_demanda_id;

    -- O trigger de sincronia limpa despachado_em a partir daqui.
    UPDATE public.demandas_producao
       SET status = 'CANCELADO',
           updated_at = now(),
           escopo_despacho = COALESCE(escopo_despacho, '{}'::jsonb) || jsonb_build_object(
               'cancelado_em', now(),
               'cancelado_por', p_user_id,
               'cancelamento_motivo', COALESCE(p_motivo, 'Nao informado'),
               'estorno_correlation_id', v_corr)
     WHERE id = p_demanda_id;

    INSERT INTO public.eventos_auditoria (tipo_evento, descricao, registro_id, dados_novos, created_at)
    VALUES ('DEMANDA_CANCELADA_COM_DEVOLUCAO',
            'Demanda cancelada; pedidos devolvidos a torre de despacho.',
            p_demanda_id,
            jsonb_build_object('demanda_id', p_demanda_id, 'demanda_codigo', v_codigo,
                               'status_anterior', v_status, 'pedidos_devolvidos', v_pedidos,
                               'estornos_estoque', v_estornos, 'motivo', p_motivo,
                               'usuario', p_user_id, 'correlation_id', v_corr),
            now());

    RETURN QUERY SELECT v_codigo, v_pedidos, v_estornos;
END;
$fn$;

COMMENT ON FUNCTION public.despacho_cancelar_demanda(integer, text, text) IS
  'Cancela a demanda, estorna as saidas de coleta por movimento compensatorio e devolve os pedidos a torre (via trigger de sincronia). Producao nao e estornada: o material foi consumido de verdade.';

-- ============================================================================
-- Exclusao definitiva: so quando nao ha rastro para preservar
-- ============================================================================

CREATE OR REPLACE FUNCTION public.despacho_excluir_demanda(
    p_demanda_id integer,
    p_user_id    text DEFAULT 'System'
)
RETURNS TABLE (out_demanda_codigo text, out_pedidos_devolvidos integer)
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_status   text;
    v_codigo   text;
    v_pedidos  integer;
    v_mov      integer;
    v_eventos  integer;
BEGIN
    SELECT d.status, d.demanda_id INTO v_status, v_codigo
      FROM public.demandas_producao d WHERE d.id = p_demanda_id FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Demanda % nao encontrada', p_demanda_id USING ERRCODE = 'no_data_found';
    END IF;

    -- Mensagem que nomeia o bloqueio, em vez do "violates foreign key
    -- constraint" que o operador nao consegue interpretar.
    SELECT count(*) INTO v_mov
      FROM public.movimentacoes_estoque m
      JOIN public.itens_demanda i ON i.id = m.item_demanda_id
     WHERE i.demanda_id = p_demanda_id;

    SELECT count(*) INTO v_eventos
      FROM public.demanda_estoque_processado WHERE demanda_id = p_demanda_id;

    IF v_mov > 0 OR v_eventos > 0 THEN
        RAISE EXCEPTION
          'Demanda % ja movimentou estoque (% movimentacoes, % registros de processamento) e nao pode ser excluida. Use o cancelamento, que estorna a coleta e devolve os pedidos a torre preservando o ledger.',
          v_codigo, v_mov, v_eventos
          USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT count(*) INTO v_pedidos
      FROM public.demandas_pedidos WHERE demanda_id = p_demanda_id;

    INSERT INTO public.eventos_auditoria (tipo_evento, descricao, registro_id, dados_novos, created_at)
    VALUES ('DEMANDA_EXCLUIDA',
            'Demanda excluida definitivamente; pedidos devolvidos a torre de despacho.',
            p_demanda_id,
            jsonb_build_object('demanda_id', p_demanda_id, 'demanda_codigo', v_codigo,
                               'status_anterior', v_status, 'pedidos_devolvidos', v_pedidos,
                               'usuario', p_user_id),
            now());

    -- CASCADE derruba itens_demanda e demandas_pedidos; o trigger de sincronia
    -- devolve os pedidos a torre.
    DELETE FROM public.demandas_producao WHERE id = p_demanda_id;

    RETURN QUERY SELECT v_codigo, v_pedidos;
END;
$fn$;

COMMENT ON FUNCTION public.despacho_excluir_demanda(integer, text) IS
  'Exclusao definitiva, permitida so para demanda sem rastro de estoque. Bloqueio devolve mensagem que nomeia o motivo e aponta o cancelamento. Pedidos voltam a torre pelo trigger de sincronia.';

GRANT EXECUTE ON FUNCTION public.despacho_cancelar_demanda(integer, text, text) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.despacho_excluir_demanda(integer, text) TO authenticated, service_role;
