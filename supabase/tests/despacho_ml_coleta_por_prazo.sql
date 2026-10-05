-- Regressao: Mercado Livre usa a ultima coleta viavel antes do SLA; Shopee
-- continua exatamente no algoritmo de pagamento + corte.
-- Executar apos as migrations com psql -v ON_ERROR_STOP=1 -f este_arquivo.
BEGIN;

DO $test$
DECLARE
    v_suffix text := txid_current()::text;
    v_integration_ml integer;
    v_integration_shopee integer;
    v_modalidade_ml integer;
    v_modalidade_shopee integer;
    v_ml record;
    v_shopee_atual record;
    v_shopee_esperado record;
    v_agora timestamptz := '2026-10-02T09:00:00-03:00'::timestamptz;
    v_referencia timestamptz := '2026-10-02T08:00:00-03:00'::timestamptz;
BEGIN
    INSERT INTO public.installed_integrations (module_id, instance_name, is_active)
    VALUES ('mercadolivre', 'Teste prazo ML ' || v_suffix, true)
    RETURNING id INTO v_integration_ml;

    INSERT INTO public.installed_integrations (module_id, instance_name, is_active)
    VALUES ('shopee', 'Teste prazo Shopee ' || v_suffix, true)
    RETURNING id INTO v_integration_shopee;

    INSERT INTO public.modalidades_logisticas (
        module_id, codigo, nome, tipo_prazo, corte_horario, ativo
    ) VALUES (
        'mercadolivre', 'TEST-' || v_suffix, 'Teste ML', 'FIXO', '13:00', true
    ) RETURNING id INTO v_modalidade_ml;

    INSERT INTO public.modalidades_logisticas (
        module_id, codigo, nome, tipo_prazo, corte_horario, ativo
    ) VALUES (
        'shopee', 'TEST-' || v_suffix, 'Teste Shopee', 'FIXO', '13:00', true
    ) RETURNING id INTO v_modalidade_shopee;

    INSERT INTO public.regras_logisticas_integracao (
        marketplace_integration_id, modalidade, tipo_envio, horario_limite,
        horario_corte, horario_coleta, dias_semana, prioridade_uso, ativo,
        modalidade_id, coleta_dia_offset
    ) VALUES
        (v_integration_ml, 'STANDARD', 'COLETA_LOCAL', '17:00', '13:00', '17:00',
         ARRAY[1,2,3,4,5,6,7]::smallint[], 1, true, v_modalidade_ml, 0),
        (v_integration_shopee, 'STANDARD', 'COLETA_LOCAL', '17:00', '13:00', '17:00',
         ARRAY[1,2,3,4,5,6,7]::smallint[], 1, true, v_modalidade_shopee, 0);

    IF to_regclass('public.regra_logistica_modalidades') IS NOT NULL THEN
        EXECUTE 'INSERT INTO public.regra_logistica_modalidades(regra_id, modalidade_id) '
             || 'SELECT id, modalidade_id FROM public.regras_logisticas_integracao '
             || 'WHERE marketplace_integration_id IN ($1, $2) ON CONFLICT DO NOTHING'
        USING v_integration_ml, v_integration_shopee;
    END IF;

    SELECT * INTO v_ml
      FROM public.despacho_coleta_do_pedido(
          'mercadolivre', v_modalidade_ml, v_integration_ml, v_referencia,
          '2026-10-06T00:00:00-03:00'::timestamptz, v_agora
      );
    IF v_ml.coleta_em IS DISTINCT FROM '2026-10-06T17:00:00-03:00'::timestamptz THEN
        RAISE EXCEPTION 'ML deveria usar a ultima coleta ate 06/10, recebeu %', v_ml.coleta_em;
    END IF;

    SELECT * INTO v_ml
      FROM public.despacho_coleta_do_pedido(
          'mercadolivre', v_modalidade_ml, v_integration_ml, v_referencia,
          '2026-10-06T12:00:00-03:00'::timestamptz, v_agora
      );
    IF v_ml.coleta_em IS DISTINCT FROM '2026-10-05T17:00:00-03:00'::timestamptz THEN
        RAISE EXCEPTION 'ML nao pode ultrapassar o prazo: esperado 05/10, recebeu %', v_ml.coleta_em;
    END IF;

    SELECT * INTO v_ml
      FROM public.despacho_coleta_do_pedido(
          'mercadolivre', v_modalidade_ml, v_integration_ml, v_referencia,
          '2026-10-01T23:59:59-03:00'::timestamptz, v_agora
      );
    IF v_ml.coleta_em IS DISTINCT FROM '2026-10-02T17:00:00-03:00'::timestamptz THEN
        RAISE EXCEPTION 'ML vencido deveria cair na proxima coleta, recebeu %', v_ml.coleta_em;
    END IF;

    SELECT * INTO v_ml
      FROM public.despacho_coleta_do_pedido(
          'mercadolivre', v_modalidade_ml, v_integration_ml, v_referencia,
          '2026-10-02T12:00:00-03:00'::timestamptz, v_agora
      );
    IF v_ml.coleta_em IS DISTINCT FROM '2026-10-02T17:00:00-03:00'::timestamptz THEN
        RAISE EXCEPTION 'ML sem coleta compativel deve usar a proxima janela, recebeu %', v_ml.coleta_em;
    END IF;

    SELECT * INTO v_shopee_atual
      FROM public.despacho_coleta_do_pedido(
          'shopee', v_modalidade_shopee, v_integration_shopee, v_referencia,
          '2026-10-06T23:59:59-03:00'::timestamptz, v_agora
      );
    SELECT * INTO v_shopee_esperado
      FROM public.coleta_do_pedido(
          v_modalidade_shopee, v_integration_shopee, v_referencia, v_agora
      );
    IF ROW(v_shopee_atual.corte_em, v_shopee_atual.coleta_em, v_shopee_atual.prazo_final_em)
       IS DISTINCT FROM
       ROW(v_shopee_esperado.corte_em, v_shopee_esperado.coleta_em, v_shopee_esperado.prazo_final_em) THEN
        RAISE EXCEPTION 'A regra da Shopee mudou';
    END IF;

    -- Sem prazo informado tambem preserva o algoritmo anterior para o ML.
    SELECT * INTO v_ml
      FROM public.despacho_coleta_do_pedido(
          'mercadolivre', v_modalidade_ml, v_integration_ml, v_referencia,
          NULL, v_agora
      );
    IF ROW(v_ml.corte_em, v_ml.coleta_em, v_ml.prazo_final_em)
       IS DISTINCT FROM ROW(v_shopee_esperado.corte_em, v_shopee_esperado.coleta_em, v_shopee_esperado.prazo_final_em) THEN
        RAISE EXCEPTION 'ML sem prazo deveria preservar o fallback existente';
    END IF;
END;
$test$;

ROLLBACK;
