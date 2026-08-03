-- Lancamento de demanda a partir de um escopo de despacho.
-- Contrato: docs/specs/02-domains/despacho/spec.md, secao "Escopo composto e lancamento"
--
-- Substitui selecao pedido a pedido por (no, horizonte). A funcao roda em uma
-- unica transacao plpgsql: cria a demanda, agrega itens, vincula pedidos e
-- carimba despachado_em juntos. Se qualquer passo falhar, nada e commitado —
-- essa e a garantia que o risco "despachado_em fora de sincronia" do
-- data-model.md pede.
--
-- Retardatarios (spec): se a demanda deste escopo ja existe e ainda esta em
-- RASCUNHO ou AGUARDANDO, pedidos novos do mesmo escopo entram como lote
-- complementar (demanda_origem_id), sem alterar a demanda em producao.

DROP FUNCTION IF EXISTS public.despacho_lancar_escopo(integer, integer, text[], date, text, text, text);

CREATE FUNCTION public.despacho_lancar_escopo(
    p_integration_id integer,
    p_modalidade_id  integer,
    p_horizonte      text[],
    p_data           date,
    p_nome           text DEFAULT NULL,
    p_user_id        text DEFAULT 'System',
    p_observacoes    text DEFAULT NULL
)
-- OUT columns prefixadas com out_: "demanda_id" como nome de OUT parameter
-- colide com a coluna homonima de varias tabelas referenciadas no corpo
-- (itens_demanda, demandas_pedidos), e cada referencia precisaria de alias
-- explicito para nao falhar com "column reference is ambiguous". Prefixo
-- elimina a classe inteira do problema em vez de qualificar caso a caso.
RETURNS TABLE (
    out_demanda_id        integer,
    out_demanda_codigo    text,
    out_total_pedidos     integer,
    out_total_itens       numeric,
    out_complementar      boolean
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_pedido_ids       integer[];
    v_total_pedidos    integer;
    v_marketplace_nome text;
    v_modalidade_nome  text;
    v_modalidade_codigo varchar(50);
    v_canal_venda_id   integer;
    v_demanda_pk       integer;
    v_demanda_codigo   text;
    v_escopo           jsonb;
    v_data_entrega     date;
    v_existente_id     integer;
    v_complementar     boolean := false;
    v_total_itens      numeric := 0;
BEGIN
    -- despacho_escopo_pedidos devolve SETOF integer (sem nome de coluna);
    -- agregar o proprio valor da funcao, nao uma coluna "id" que nao existe.
    SELECT array_agg(pedido_id) INTO v_pedido_ids
      FROM public.despacho_escopo_pedidos(p_integration_id, p_modalidade_id, p_horizonte, p_data) AS pedido_id;

    v_total_pedidos := COALESCE(array_length(v_pedido_ids, 1), 0);
    IF v_total_pedidos = 0 THEN
        RAISE EXCEPTION 'Escopo vazio: nenhum pedido em aberto para integration_id=%, modalidade_id=%, horizonte=%',
            p_integration_id, p_modalidade_id, p_horizonte
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT instance_name INTO v_marketplace_nome
      FROM public.installed_integrations WHERE id = p_integration_id;
    v_marketplace_nome := COALESCE(v_marketplace_nome, 'Origem nao resolvida');

    SELECT nome, codigo INTO v_modalidade_nome, v_modalidade_codigo
      FROM public.modalidades_logisticas WHERE id = p_modalidade_id;
    v_modalidade_nome := COALESCE(v_modalidade_nome, 'Modalidade nao classificada');

    -- canal_venda_id legado: melhor esforco para compatibilidade com telas que
    -- ainda leem esse campo. Nao bloqueia se nao houver vinculo.
    SELECT p.canal_venda_id INTO v_canal_venda_id
      FROM public.pedidos p WHERE p.id = v_pedido_ids[1];

    v_data_entrega := p_data;

    v_escopo := jsonb_build_object(
        'integration_id', p_integration_id,
        'modalidade_id', p_modalidade_id,
        'horizonte', to_jsonb(p_horizonte),
        'data_operacional', p_data,
        'total_pedidos_no_lancamento', v_total_pedidos,
        'total_conferido_pelo_operador', v_total_pedidos,
        'lancado_em', now(),
        'lancado_por', p_user_id
    );

    -- Retardatario: ja existe demanda ABERTA (RASCUNHO/AGUARDANDO) para este
    -- exato escopo e data. Pedido que chegou depois vira lote complementar
    -- vinculado, a demanda original nunca e alterada.
    SELECT d.id INTO v_existente_id
      FROM public.demandas_producao d
     WHERE d.modalidade_id IS NOT DISTINCT FROM p_modalidade_id
       AND d.escopo_despacho ->> 'integration_id' = COALESCE(p_integration_id::text, '')
       AND d.escopo_despacho ->> 'data_operacional' = p_data::text
       AND d.status IN ('RASCUNHO', 'AGUARDANDO')
       AND d.demanda_origem_id IS NULL
     ORDER BY d.created_at DESC
     LIMIT 1;

    v_demanda_codigo := format('DESPACHO-%s-%s-%s',
        p_integration_id, COALESCE(v_modalidade_codigo, 'SEMMOD'), to_char(p_data, 'YYYYMMDD'));

    IF v_existente_id IS NOT NULL THEN
        v_complementar := true;
        v_demanda_codigo := v_demanda_codigo || '-COMPL-' || to_char(now(), 'HH24MISS');
    END IF;

    INSERT INTO public.demandas_producao (
        demanda_id, descricao, status, tipo_demanda, canal_venda_id,
        data_entrega, observacoes, modalidade_id, modalidade_logistica,
        is_flex, escopo_despacho, demanda_origem_id, pedido_numero
    ) VALUES (
        v_demanda_codigo,
        COALESCE(p_nome, format('%s / %s - %s', v_marketplace_nome, v_modalidade_nome, to_char(p_data, 'DD/MM'))),
        'AGUARDANDO',
        'PLATAFORMA',
        v_canal_venda_id,
        v_data_entrega,
        p_observacoes,
        p_modalidade_id,
        v_modalidade_codigo,
        (v_modalidade_codigo = 'FLEX'),
        v_escopo,
        CASE WHEN v_complementar THEN v_existente_id END,
        v_total_pedidos::text || ' pedidos'
    )
    RETURNING id INTO v_demanda_pk;

    -- Itens agregados por produto_id (fallback sku quando produto_id e nulo,
    -- que e o caso normal quando o item nao tem vinculo interno — spec:
    -- "degradar, nao bloquear". A demanda nasce mesmo assim; so a
    -- reconciliacao de estoque desse item nao ocorre).
    INSERT INTO public.itens_demanda (demanda_id, produto_id, sku, descricao, quantidade)
    SELECT
        v_demanda_pk,
        ip.produto_id,
        max(ip.sku_externo),
        max(ip.descricao),
        sum(ip.quantidade)
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = ANY(v_pedido_ids)
     GROUP BY ip.produto_id, COALESCE(ip.sku_externo, ip.descricao, ip.produto_id::text);

    -- Qualificado: o OUT parameter da funcao tambem se chama demanda_id e
    -- colide com a coluna homonima sem o alias da tabela.
    SELECT COALESCE(sum(idm.quantidade), 0) INTO v_total_itens
      FROM public.itens_demanda idm WHERE idm.demanda_id = v_demanda_pk;

    INSERT INTO public.demandas_pedidos (demanda_id, pedido_id)
    SELECT v_demanda_pk, unnest(v_pedido_ids)
    ON CONFLICT (demanda_id, pedido_id) DO NOTHING;

    UPDATE public.pedidos
       SET despachado_em = now()
     WHERE id = ANY(v_pedido_ids);

    RETURN QUERY SELECT v_demanda_pk, v_demanda_codigo, v_total_pedidos, v_total_itens, v_complementar;
END;
$$;

COMMENT ON FUNCTION public.despacho_lancar_escopo(integer, integer, text[], date, text, text, text) IS
  'Uma transacao: cria demanda, agrega itens, vincula pedidos, carimba despachado_em. Escopo vazio levanta excecao em vez de criar demanda fantasma. Retardatario de escopo com demanda ja AGUARDANDO/RASCUNHO gera lote complementar via demanda_origem_id.';
