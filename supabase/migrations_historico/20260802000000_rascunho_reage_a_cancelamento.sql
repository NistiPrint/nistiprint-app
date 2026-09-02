-- Rascunho reage a cancelamento do marketplace
--
-- Problema observado em 02/08/2026: 398 pedidos cancelados estavam vinculados a
-- demandas em RASCUNHO. Se qualquer um desses rascunhos fosse publicado, a
-- producao receberia pedidos que o cliente ja cancelou — papel, capa e miolo
-- gastos em algo que nao vai ser enviado.
--
-- O RPC `process_marketplace_order_effect` ja tratava o caso da demanda em
-- producao: gera alerta e marca `requer_revisao`. Mas o laco filtrava
-- `d.status IN ('AGUARDANDO','EM_PRODUCAO','COLETA_PARCIAL','COLETADO')`, e
-- todas as 39 demandas existentes estao em RASCUNHO. Resultado: 262 efeitos
-- marcados como `processed` com zero alertas gerados. Nao era bug do consumidor
-- — era um caso nao coberto, que se manifestava como sucesso silencioso.
--
-- A resposta certa difere por estagio:
--
--   RASCUNHO  -> o pedido ainda nao virou trabalho. Remove-se do rascunho e
--                ajusta-se a quantidade. Alerta informativo, sem exigir acao.
--   PRODUCAO  -> o trabalho pode ja ter comecado. Nao se remove nada pelas
--                costas do operador: alerta que exige acao, como antes.

CREATE OR REPLACE FUNCTION public.process_marketplace_order_effect(p_effect_id bigint)
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_effect public.marketplace_order_effects%ROWTYPE;
  v_link RECORD;
  v_alert_count INTEGER := 0;
  v_removed_count INTEGER := 0;
  v_is_returned BOOLEAN;
  v_qtd_pedido INTEGER;
  v_rotulo TEXT;
BEGIN
  SELECT * INTO v_effect
  FROM public.marketplace_order_effects
  WHERE id = p_effect_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'marketplace_order_effect % not found', p_effect_id;
  END IF;
  IF v_effect.status = 'processed' THEN
    RETURN jsonb_build_object('effect_id', p_effect_id, 'status', 'processed', 'alerts', 0);
  END IF;

  v_is_returned := COALESCE(v_effect.payload->>'lifecycle_stage', '') = 'returned';
  v_rotulo := CASE WHEN v_is_returned THEN 'devolvido' ELSE 'cancelado' END;

  -- ---------------------------------------------------------------------
  -- Demandas ja publicadas: alerta que exige acao humana.
  -- ---------------------------------------------------------------------
  FOR v_link IN
    SELECT dp.demanda_id
    FROM public.demandas_pedidos dp
    JOIN public.demandas_producao d ON d.id = dp.demanda_id
    WHERE dp.pedido_id = v_effect.pedido_id
      AND d.status IN ('AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'COLETADO')
  LOOP
    INSERT INTO public.alertas_demanda (
      demanda_id, tipo_alerta, severidade, titulo, mensagem,
      dados_impacto, requer_acao, created_at
    ) VALUES (
      v_link.demanda_id,
      CASE WHEN v_is_returned THEN 'PEDIDO_DEVOLVIDO' ELSE 'PEDIDO_CANCELADO' END,
      'media',
      CASE WHEN v_is_returned THEN 'Pedido devolvido na demanda' ELSE 'Pedido cancelado na demanda' END,
      format(
        'Pedido %s foi %s pelo marketplace; revise a demanda.',
        COALESCE(v_effect.payload->>'external_order_id', v_effect.pedido_id::text),
        v_rotulo
      ),
      jsonb_build_object(
        'pedido_id', v_effect.pedido_id,
        'transition_id', v_effect.transition_id,
        'effect_id', v_effect.id,
        'lifecycle_stage', v_effect.payload->>'lifecycle_stage'
      ),
      true,
      now()
    );
    UPDATE public.demandas_producao
       SET requer_revisao = true, updated_at = now()
     WHERE id = v_link.demanda_id;
    v_alert_count := v_alert_count + 1;
  END LOOP;

  -- ---------------------------------------------------------------------
  -- Rascunhos: o pedido sai antes de virar trabalho.
  -- ---------------------------------------------------------------------
  FOR v_link IN
    SELECT dp.id AS vinculo_id, dp.demanda_id
    FROM public.demandas_pedidos dp
    JOIN public.demandas_producao d ON d.id = dp.demanda_id
    WHERE dp.pedido_id = v_effect.pedido_id
      AND d.status = 'RASCUNHO'
  LOOP
    SELECT COALESCE(SUM(ip.quantidade), 0)::INTEGER INTO v_qtd_pedido
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = v_effect.pedido_id;

    DELETE FROM public.demandas_pedidos WHERE id = v_link.vinculo_id;

    -- `GREATEST(...,0)`: a quantidade da demanda e um acumulado mantido pelo
    -- servico de consolidacao. Se ele e o pedido divergirem, o saldo nunca
    -- pode ficar negativo — um numero negativo aqui contamina o planejamento
    -- de capacidade silenciosamente.
    UPDATE public.demandas_producao
       SET quantidade = GREATEST(COALESCE(quantidade, 0) - COALESCE(v_qtd_pedido, 0), 0),
           updated_at = now()
     WHERE id = v_link.demanda_id;

    INSERT INTO public.alertas_demanda (
      demanda_id, tipo_alerta, severidade, titulo, mensagem,
      dados_impacto, requer_acao, created_at
    ) VALUES (
      v_link.demanda_id,
      'PEDIDO_REMOVIDO_RASCUNHO',
      'baixa',
      format('Pedido %s removido do rascunho', v_rotulo),
      format(
        'Pedido %s foi %s pelo marketplace e saiu automaticamente do rascunho (%s un.).',
        COALESCE(v_effect.payload->>'external_order_id', v_effect.pedido_id::text),
        v_rotulo,
        COALESCE(v_qtd_pedido, 0)
      ),
      jsonb_build_object(
        'pedido_id', v_effect.pedido_id,
        'transition_id', v_effect.transition_id,
        'effect_id', v_effect.id,
        'quantidade_removida', COALESCE(v_qtd_pedido, 0),
        'lifecycle_stage', v_effect.payload->>'lifecycle_stage'
      ),
      false,
      now()
    );
    v_removed_count := v_removed_count + 1;
  END LOOP;

  INSERT INTO public.eventos_pedido (
    pedido_id, tipo_evento, descricao, status_para, metadata, created_at
  ) VALUES (
    v_effect.pedido_id,
    CASE WHEN v_is_returned THEN 'ORDER_RETURNED_MARKETPLACE' ELSE 'ORDER_CANCELLED_MARKETPLACE' END,
    CASE WHEN v_is_returned THEN 'Pedido devolvido pelo marketplace' ELSE 'Pedido cancelado pelo marketplace' END,
    CASE WHEN v_is_returned THEN '8' ELSE '7' END,
    jsonb_build_object(
      'transition_id', v_effect.transition_id,
      'effect_id', v_effect.id,
      'alertas_demanda', v_alert_count,
      'removido_de_rascunhos', v_removed_count
    ),
    now()
  );

  UPDATE public.marketplace_order_effects
     SET status = 'processed', processed_at = now(), updated_at = now(),
         attempt_count = attempt_count + 1, last_error = NULL
   WHERE id = p_effect_id;

  RETURN jsonb_build_object(
    'effect_id', p_effect_id,
    'status', 'processed',
    'alerts', v_alert_count,
    'removed_from_drafts', v_removed_count
  );
END;
$function$;


-- ---------------------------------------------------------------------------
-- Backfill: limpa os cancelados que ja estao nos rascunhos.
--
-- Os efeitos correspondentes ja foram marcados como `processed` na execucao
-- anterior (que nao cobria RASCUNHO), entao reprocessa-los nao adiantaria — o
-- RPC retorna cedo em `status = 'processed'`. A limpeza e feita aqui uma vez.
-- ---------------------------------------------------------------------------
DO $backfill$
DECLARE
  v_row RECORD;
  v_qtd INTEGER;
  v_total INTEGER := 0;
BEGIN
  FOR v_row IN
    SELECT dp.id AS vinculo_id, dp.demanda_id, dp.pedido_id, p.situacao_pedido_id
      FROM public.demandas_pedidos dp
      JOIN public.demandas_producao d ON d.id = dp.demanda_id
      JOIN public.pedidos p ON p.id = dp.pedido_id
     WHERE d.status = 'RASCUNHO'
       AND p.situacao_pedido_id IN (7, 8)   -- 7 Cancelado, 8 Devolvido
  LOOP
    SELECT COALESCE(SUM(ip.quantidade), 0)::INTEGER INTO v_qtd
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = v_row.pedido_id;

    DELETE FROM public.demandas_pedidos WHERE id = v_row.vinculo_id;

    UPDATE public.demandas_producao
       SET quantidade = GREATEST(COALESCE(quantidade, 0) - COALESCE(v_qtd, 0), 0),
           updated_at = now()
     WHERE id = v_row.demanda_id;

    INSERT INTO public.alertas_demanda (
      demanda_id, tipo_alerta, severidade, titulo, mensagem,
      dados_impacto, requer_acao, created_at
    ) VALUES (
      v_row.demanda_id,
      'PEDIDO_REMOVIDO_RASCUNHO',
      'baixa',
      'Pedido cancelado removido do rascunho (limpeza)',
      format(
        'Pedido %s estava em situacao terminal e saiu do rascunho na limpeza de 02/08 (%s un.).',
        v_row.pedido_id, COALESCE(v_qtd, 0)
      ),
      jsonb_build_object(
        'pedido_id', v_row.pedido_id,
        'situacao_pedido_id', v_row.situacao_pedido_id,
        'quantidade_removida', COALESCE(v_qtd, 0),
        'origem', 'backfill_20260802'
      ),
      false,
      now()
    );
    v_total := v_total + 1;
  END LOOP;

  RAISE NOTICE 'Backfill: % vinculos de pedidos terminais removidos de rascunhos', v_total;
END;
$backfill$;
