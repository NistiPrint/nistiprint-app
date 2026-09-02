-- RPCs do fechamento automatico de janela.
-- Contrato: docs/specs/02-domains/despacho/spec.md

-- --------------------------------------------------------------------------
-- Catch-up: que janela venceu e ainda nao foi processada?
-- --------------------------------------------------------------------------
-- O job pergunta isto ao banco em vez de assumir que rodou no instante certo.
-- E o que torna aceitavel agendar uma entrada de cron por horario cadastrado:
-- se o schedule sair de sincronia com a aba Logistica, ou o worker passar um
-- tempo fora, a janela e recuperada na proxima execucao em vez de sumir.

CREATE OR REPLACE FUNCTION public.janelas_despacho_vencidas(
    p_agora timestamptz DEFAULT now(),
    p_desde interval    DEFAULT interval '24 hours'
)
RETURNS TABLE (
    integration_id integer,
    modalidade_id  integer,
    tipo           text,
    janela_em      timestamptz
)
LANGUAGE sql
STABLE
AS $fn$
    WITH regras AS (
        SELECT r.marketplace_integration_id AS integration_id,
               r.modalidade_id,
               r.horario_corte,
               r.horario_coleta,
               COALESCE(r.coleta_dia_offset, 0) AS offset_dias,
               COALESCE(r.dias_semana, ARRAY[1,2,3,4,5,6,7]) AS dias
          FROM public.regras_logisticas_integracao r
          JOIN public.modalidades_logisticas m ON m.id = r.modalidade_id
         WHERE r.ativo AND m.ativo AND m.tipo_prazo = 'FIXO'
           AND m.entra_na_torre
           AND r.horario_corte IS NOT NULL
    ),
    dias AS (
        SELECT generate_series(
                   ((p_agora - p_desde) AT TIME ZONE 'America/Sao_Paulo')::date,
                   (p_agora AT TIME ZONE 'America/Sao_Paulo')::date,
                   interval '1 day'
               )::date AS dia
    ),
    candidatas AS (
        SELECT r.integration_id, r.modalidade_id, g.tipo, g.janela_em
          FROM regras r
          CROSS JOIN dias d
          CROSS JOIN LATERAL (VALUES
                ('CORTE',  ((d.dia + r.horario_corte) AT TIME ZONE 'America/Sao_Paulo')),
                ('COLETA', ((d.dia + r.offset_dias + COALESCE(r.horario_coleta, r.horario_corte))
                             AT TIME ZONE 'America/Sao_Paulo'))
          ) AS g(tipo, janela_em)
         WHERE EXTRACT(isodow FROM d.dia)::integer = ANY (r.dias)
           AND g.janela_em <= p_agora
           AND g.janela_em >  p_agora - p_desde
    )
    SELECT c.integration_id, c.modalidade_id, c.tipo::text, c.janela_em
      FROM candidatas c
     WHERE NOT EXISTS (
           SELECT 1 FROM public.janelas_despacho_execucoes e
            WHERE e.integration_id = c.integration_id
              AND e.modalidade_id  = c.modalidade_id
              AND e.tipo           = c.tipo
              AND e.janela_em      = c.janela_em
     )
     ORDER BY c.janela_em, c.integration_id, c.modalidade_id;
$fn$;

COMMENT ON FUNCTION public.janelas_despacho_vencidas(timestamptz, interval) IS
  'Janelas de corte/coleta ja vencidas e nao processadas. E o catch-up: o job nao depende de ter rodado no instante exato.';

-- --------------------------------------------------------------------------
-- Fechamento do corte
-- --------------------------------------------------------------------------
-- A guarda de idempotencia mora AQUI, nao no chamador. Idempotencia que depende
-- da disciplina de quem chama nao e idempotencia: bastava invocar a funcao duas
-- vezes — retry, execucao manual, dois workers na mesma janela — para nascerem
-- duas demandas com os mesmos pedidos.
--
-- A janela e reservada antes do trabalho comecar, e o unique index arbitra.

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
BEGIN
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

    -- Mesmo predicado da torre. Nao existe horizonte aqui: no corte, tudo o que
    -- estava pendente entra nesta coleta.
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
       );

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

    v_codigo := format('CORTE-%s-%s-%s',
        p_integration_id, COALESCE(v_modalidade_cod, 'SEMMOD'),
        to_char(p_janela_em AT TIME ZONE 'America/Sao_Paulo', 'YYYYMMDD-HH24MI'));

    INSERT INTO public.demandas_producao (
        demanda_id, descricao, status, tipo_demanda, canal_venda_id,
        data_entrega, modalidade_id, modalidade_logistica, is_flex,
        escopo_despacho, pedido_numero
    ) VALUES (
        v_codigo,
        format('%s / %s - corte %s', COALESCE(v_marketplace, 'Origem nao resolvida'),
               COALESCE(v_modalidade_nome, 'Modalidade nao classificada'),
               to_char(p_janela_em AT TIME ZONE 'America/Sao_Paulo', 'DD/MM HH24:MI')),
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
            'janela_em', p_janela_em,
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

    -- `despachado_em` nao e carimbado: rascunho nao e despacho. O pedido
    -- continua na torre ate alguem publicar.
    UPDATE public.janelas_despacho_execucoes
       SET demanda_id = v_demanda_pk, qtd_pedidos = v_qtd, observacao = NULL
     WHERE id = v_execucao_id;

    RETURN QUERY SELECT v_demanda_pk, v_codigo, v_qtd;
END;
$fn$;

COMMENT ON FUNCTION public.despacho_fechar_corte(integer, integer, timestamptz, text) IS
  'Fecha o lote de um corte criando demanda RASCUNHO, uma unica vez por janela. Reserva a janela antes de trabalhar: chamada repetida ou concorrente nao cria segundo lote. Nao publica e nao carimba despachado_em.';

-- --------------------------------------------------------------------------
-- Recalculo dos compromissos
-- --------------------------------------------------------------------------
-- A torre NAO depende disto: ela calcula na leitura. Existe para os
-- consumidores que leem `pedidos.compromisso_logistico_em` direto — painel de
-- producao, ordenacao de demandas — e que veriam o valor do ciclo anterior.

CREATE OR REPLACE FUNCTION public.despacho_recalcular_compromissos()
RETURNS integer
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_qtd integer;
BEGIN
    WITH alvo AS (
        SELECT p.id, j.corte_em
          FROM public.pedidos p
          JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
          CROSS JOIN LATERAL public.proxima_janela_logistica(
                        p.modalidade_logistica_id, p.marketplace_integration_id, now()
                    ) j
         WHERE p.despachado_em IS NULL
           AND p.situacao_pedido_id IN (2, 3, 4)
           AND m.tipo_prazo = 'FIXO'
           AND p.compromisso_logistico_em IS DISTINCT FROM j.corte_em
    )
    UPDATE public.pedidos p
       SET compromisso_logistico_em = a.corte_em
      FROM alvo a
     WHERE p.id = a.id;

    GET DIAGNOSTICS v_qtd = ROW_COUNT;
    RETURN v_qtd;
END;
$fn$;

COMMENT ON FUNCTION public.despacho_recalcular_compromissos() IS
  'Regrava compromisso_logistico_em dos pedidos FIXO pendentes. So para consumidores legados: a torre calcula na leitura e nao depende desta rotina.';

GRANT EXECUTE ON FUNCTION public.janelas_despacho_vencidas(timestamptz, interval) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_fechar_corte(integer, integer, timestamptz, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_recalcular_compromissos() TO authenticated;

-- --------------------------------------------------------------------------
-- Baseline
-- --------------------------------------------------------------------------
-- Registra como processadas todas as janelas ja vencidas na ativacao, sem
-- criar lote. Sem isso, a primeira execucao do job criaria rascunhos
-- retroativos de todos os cortes do ultimo dia de uma vez.

INSERT INTO public.janelas_despacho_execucoes (
    integration_id, modalidade_id, tipo, janela_em, qtd_pedidos, observacao
)
SELECT v.integration_id, v.modalidade_id, v.tipo, v.janela_em, 0,
       'Baseline na ativacao do fechamento automatico; nenhum lote retroativo criado'
  FROM public.janelas_despacho_vencidas(now(), interval '30 days') v
ON CONFLICT DO NOTHING;
