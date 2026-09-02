-- A demanda carrega as proprias janelas de saida.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## Por que congelar as janelas na demanda
--
-- Um lote fechado as 13h de hoje nao pode ser julgado atrasado por um horario
-- que alguem editou na aba Logistica amanha. `escopo_despacho.janelas` guarda
-- as saidas como estavam no fechamento; `prazo_final_em` e a ultima delas.
--
-- ## Atraso e medido pela ULTIMA saida
--
-- Este e o ponto operacional: um lote Shopee Comum com coleta local as 17h e
-- entrega em ponto de coleta as 19h que teve coleta PARCIAL as 17h continua no
-- prazo. Ainda ha caminhao. Marcar a demanda como atrasada as 17h01 diria ao
-- operador que ele falhou quando ele ainda tem duas horas para levar o resto.
--
-- ## O lote e so o que foi pago ate o corte
--
-- O filtro por `data_pagamento_marketplace <= corte` e o saneamento que o
-- operador nao deveria fazer na mao: pedido pago 13h05 pertence a proxima
-- coleta, e arrasta-lo para este lote seria produzir com prazo errado.

CREATE OR REPLACE FUNCTION public.despacho_fechar_corte(
    p_integration_id integer,
    p_modalidade_id  integer,
    p_janela_em      timestamptz,
    p_user_id        text DEFAULT 'Sistema'
)
RETURNS TABLE (out_demanda_id integer, out_demanda_codigo text, out_qtd_pedidos integer)
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_pedido_ids       integer[];
    v_qtd              integer;
    v_marketplace      text;
    v_modalidade_nome  text;
    v_modalidade_cod   varchar(50);
    v_canal_venda_id   integer;
    v_demanda_pk       integer;
    v_codigo           text;
    v_execucao_id      bigint;
    v_janelas          jsonb;
    v_prazo_final      timestamptz;
BEGIN
    -- Reserva a janela antes de trabalhar: o unique index arbitra e chamada
    -- repetida ou concorrente nao cria segundo lote.
    INSERT INTO public.janelas_despacho_execucoes (
        integration_id, modalidade_id, tipo, janela_em, qtd_pedidos, observacao
    ) VALUES (
        p_integration_id, p_modalidade_id, 'CORTE', p_janela_em, 0, 'Fechamento em andamento'
    )
    ON CONFLICT (integration_id, modalidade_id, tipo, janela_em) DO NOTHING
    RETURNING id INTO v_execucao_id;

    IF v_execucao_id IS NULL THEN
        RAISE NOTICE 'Janela de corte ja processada: integration=% modalidade=% em %',
            p_integration_id, p_modalidade_id, p_janela_em;
        RETURN;
    END IF;

    SELECT array_agg(p.id ORDER BY p.data_limite_envio NULLS LAST, p.id)
      INTO v_pedido_ids
      FROM public.pedidos p
      LEFT JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
       AND p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id    IS NOT DISTINCT FROM p_modalidade_id
       AND NOT EXISTS (
             SELECT 1 FROM public.demandas_pedidos dp
               JOIN public.demandas_producao d ON d.id = dp.demanda_id
              WHERE dp.pedido_id = p.id
                AND d.status NOT IN ('CANCELADO', 'Cancelado')
       )
       -- So o lote deste corte. Pedido pago depois pertence a proxima coleta e
       -- nao pode ser arrastado para ca.
       AND COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda) <= p_janela_em;

    v_qtd := COALESCE(array_length(v_pedido_ids, 1), 0);

    -- Corte sem pedido nao e erro: e um dia sem venda naquela modalidade.
    IF v_qtd = 0 THEN
        UPDATE public.janelas_despacho_execucoes
           SET observacao = 'Nenhum pedido pendente no corte'
         WHERE id = v_execucao_id;
        RETURN;
    END IF;

    SELECT instance_name INTO v_marketplace
      FROM public.installed_integrations WHERE id = p_integration_id;
    SELECT nome, codigo INTO v_modalidade_nome, v_modalidade_cod
      FROM public.modalidades_logisticas WHERE id = p_modalidade_id;
    SELECT p.canal_venda_id INTO v_canal_venda_id
      FROM public.pedidos p WHERE p.id = v_pedido_ids[1];

    SELECT jsonb_agg(jsonb_build_object(
               'tipo_envio', j.tipo_envio,
               'em', j.coleta_em,
               'ponto_coleta_id', j.ponto_coleta_id,
               'ponto_nome', j.ponto_nome
           ) ORDER BY j.coleta_em),
           max(j.coleta_em)
      INTO v_janelas, v_prazo_final
      FROM public.janelas_logisticas(
              p_modalidade_id, p_integration_id,
              (p_janela_em AT TIME ZONE 'America/Sao_Paulo')::date
           ) j;

    v_codigo := format('CORTE-%s-%s-%s',
        p_integration_id, COALESCE(v_modalidade_cod, 'SEMMOD'),
        to_char(p_janela_em AT TIME ZONE 'America/Sao_Paulo', 'YYYYMMDD-HH24MI'));

    INSERT INTO public.demandas_producao (
        demanda_id, descricao, status, tipo_demanda, canal_venda_id,
        data_entrega, modalidade_id, modalidade_logistica, is_flex,
        escopo_despacho, pedido_numero
    ) VALUES (
        v_codigo,
        format('%s / %s - coleta %s', COALESCE(v_marketplace, 'Origem nao resolvida'),
               COALESCE(v_modalidade_nome, 'Modalidade nao classificada'),
               to_char((v_janelas->0->>'em')::timestamptz AT TIME ZONE 'America/Sao_Paulo', 'DD/MM HH24:MI')),
        -- RASCUNHO, nunca publicada: conferir contra o painel do marketplace e
        -- o proposito da torre, e um job nao pode fazer isso.
        'RASCUNHO',
        'PLATAFORMA',
        v_canal_venda_id,
        (p_janela_em AT TIME ZONE 'America/Sao_Paulo')::date,
        p_modalidade_id,
        v_modalidade_cod,
        (v_modalidade_cod = 'FLEX'),
        jsonb_build_object(
            'integration_id', p_integration_id,
            'modalidade_id', p_modalidade_id,
            'origem', 'fechamento_automatico_de_corte',
            'corte_em', p_janela_em,
            'janelas', COALESCE(v_janelas, '[]'::jsonb),
            -- A ultima saida e o que define atraso. Coleta parcial na primeira
            -- janela nao atrasa a demanda: ainda ha caminhao.
            'prazo_final_em', v_prazo_final,
            'total_pedidos_no_fechamento', v_qtd,
            'fechado_por', p_user_id
        ),
        v_qtd::text || ' pedidos'
    ) RETURNING id INTO v_demanda_pk;

    INSERT INTO public.itens_demanda (demanda_id, produto_id, sku, descricao, quantidade)
    SELECT v_demanda_pk, ip.produto_id, max(ip.sku_externo), max(ip.descricao), sum(ip.quantidade)
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = ANY(v_pedido_ids)
     GROUP BY ip.produto_id, COALESCE(ip.sku_externo, ip.descricao, ip.produto_id::text);

    INSERT INTO public.demandas_pedidos (demanda_id, pedido_id)
    SELECT v_demanda_pk, unnest(v_pedido_ids)
    ON CONFLICT (demanda_id, pedido_id) DO NOTHING;

    UPDATE public.janelas_despacho_execucoes
       SET demanda_id = v_demanda_pk, qtd_pedidos = v_qtd, observacao = NULL
     WHERE id = v_execucao_id;

    RETURN QUERY SELECT v_demanda_pk, v_codigo, v_qtd;
END;
$fn$;

COMMENT ON FUNCTION public.despacho_fechar_corte(integer, integer, timestamptz, text) IS
  'Fecha o lote de um corte criando demanda RASCUNHO com as janelas de saida congeladas em escopo_despacho. O lote inclui apenas pedidos pagos ate o corte. prazo_final_em e a ultima saida: coleta parcial na primeira janela nao atrasa a demanda.';

CREATE OR REPLACE FUNCTION public.demanda_atrasada(p_demanda_id integer, p_agora timestamptz DEFAULT now())
RETURNS boolean
LANGUAGE sql
STABLE
AS $fn$
    SELECT CASE
             WHEN d.status IN ('CONCLUIDO', 'Concluído', 'CANCELADO', 'Cancelado') THEN false
             WHEN d.escopo_despacho ->> 'prazo_final_em' IS NULL THEN false
             ELSE (d.escopo_despacho ->> 'prazo_final_em')::timestamptz < p_agora
           END
      FROM public.demandas_producao d
     WHERE d.id = p_demanda_id;
$fn$;

COMMENT ON FUNCTION public.demanda_atrasada(integer, timestamptz) IS
  'Atraso e medido pela ULTIMA saida do lote, nao pela primeira. Uma demanda com coleta 17h e envio 19h que teve coleta parcial as 17h continua no prazo ate as 19h.';

GRANT EXECUTE ON FUNCTION public.demanda_atrasada(integer, timestamptz) TO anon, authenticated;
