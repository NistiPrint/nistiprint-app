-- O lote vindo de planilha materializava seus itens por conta propria.
--
-- `despacho_lancar_pedidos` nasceu (20260831000000) com um INSERT ... SELECT
-- proprio: agrupava por (produto_id, sku) e descobria o miolo procurando
-- '%MIOLO%' no nome, no SKU ou no tipo de material do componente da ficha.
--
-- O fluxo da torre nunca fez isso. Ele chama `despacho_materializar_itens` ->
-- `despacho_consolidar_pedidos`, que resolve o produto interno em tres saltos
-- (item ja vinculado -> produtos_externos.codigo_externo -> produtos.sku), acha
-- o miolo pela categoria cadastrada em `producao_miolos_category_id`
-- respeitando `herdar_bom_pai` e o fallback por `sku_produto_pai`, agrupa por
-- (titulo, sku, variacao, miolo) e ordena por carga de miolo decrescente.
--
-- Duas consolidacoes para a mesma pergunta significam que o mesmo conjunto de
-- pedidos produzia uma ordem de producao diferente conforme tivesse vindo da
-- planilha ou do card da torre. E o caminho proprio ainda deixava de gravar:
--
--   ordem, variacao, sku_externo, quantidade_planejada, miolo_chave,
--   miolo_origem, contabiliza_estoque
--
-- que sao exatamente as colunas que a tela le para agrupar por miolo e para
-- avisar que uma linha produz sem movimentar estoque — por isso a consolidacao
-- do arquivo aparecia vazia. Alem disso nao escrevia `demandas_item_origem`,
-- que e o que liga a linha de producao de volta ao item do pedido.
--
-- Aqui a funcao passa a ser so o que ela deveria ter sido desde o inicio:
-- recorte + guarda de rascunho + delegacao para a materializacao canonica.

CREATE OR REPLACE FUNCTION public.despacho_lancar_pedidos(
    p_pedido_ids integer[],
    p_nome text DEFAULT NULL,
    p_user_id text DEFAULT 'System',
    p_observacoes text DEFAULT NULL,
    p_escopo jsonb DEFAULT '{}'::jsonb
)
RETURNS TABLE (
    out_demanda_id integer,
    out_demanda_codigo text,
    out_total_pedidos integer,
    out_total_itens numeric,
    out_complementar boolean,
    out_ja_em_rascunho jsonb
)
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    v_ids            integer[];
    v_todos_ids      integer[];
    v_conflitos      jsonb;
    v_conferencia    text := NULLIF(p_escopo ->> 'conferencia_id', '');
    v_demanda        integer;
    v_codigo         text;
    v_integration_id integer;
    v_modalidade_id  integer;
    v_codigo_mod     varchar(50);
    v_canal_id       integer;
    v_marketplace    text;
    v_nos            jsonb;
    v_somou          boolean := false;
    v_total_itens    numeric := 0;
BEGIN
    -- 1. Do que o chamador pediu, o que ainda esta pendente de despacho.
    SELECT array_agg(DISTINCT p.id ORDER BY p.id) INTO v_ids
      FROM public.pedidos p
     WHERE p.id = ANY(COALESCE(p_pedido_ids, '{}'::integer[]))
       AND p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4);

    -- 2. O rascunho desta conferencia, se ja existir. Relancar a mesma planilha
    --    SOMA nele; nao cria um segundo lote para o mesmo recorte.
    IF v_conferencia IS NOT NULL THEN
        SELECT d.id INTO v_demanda
          FROM public.demandas_producao d
         WHERE d.status = 'RASCUNHO'
           AND d.escopo_despacho ->> 'conferencia_id' = v_conferencia
         ORDER BY d.id DESC LIMIT 1;
        v_somou := v_demanda IS NOT NULL;
    END IF;

    -- 3. Guarda: um pedido nao pode estar em dois rascunhos abertos. O proprio
    --    rascunho desta conferencia nao conta como conflito — senao relancar
    --    seria recusado pelo lote que ele mesmo criou.
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'pedido_id',      dp.pedido_id,
                'demanda_id',     dp.demanda_id,
                'demanda_codigo', d.demanda_id,
                'descricao',      d.descricao
           ) ORDER BY dp.pedido_id), '[]'::jsonb)
      INTO v_conflitos
      FROM public.demandas_pedidos dp
      JOIN public.demandas_producao d ON d.id = dp.demanda_id
     WHERE dp.pedido_id = ANY(COALESCE(v_ids, '{}'::integer[]))
       AND d.status = 'RASCUNHO'
       AND (v_demanda IS NULL OR dp.demanda_id <> v_demanda);

    SELECT array_agg(x.pedido_id ORDER BY x.pedido_id) INTO v_ids
      FROM (
        SELECT unnest(COALESCE(v_ids, '{}'::integer[])) AS pedido_id
        EXCEPT
        SELECT (item ->> 'pedido_id')::integer
          FROM jsonb_array_elements(v_conflitos) item
      ) x;

    IF COALESCE(array_length(v_ids, 1), 0) = 0 AND NOT v_somou THEN
        RAISE EXCEPTION 'Escopo vazio: nenhum pedido disponivel para lancamento'
            USING ERRCODE = 'no_data_found', DETAIL = v_conflitos::text;
    END IF;

    -- 4. Contexto do lote, derivado do conjunto real. O arquivo pode atravessar
    --    mais de um no da torre; o lote e nomeado pelo majoritario e guarda a
    --    composicao inteira em escopo_despacho.nos para a tela poder avisar.
    SELECT t.marketplace_integration_id, t.modalidade_logistica_id, t.canal_venda_id
      INTO v_integration_id, v_modalidade_id, v_canal_id
      FROM (
        SELECT p.marketplace_integration_id, p.modalidade_logistica_id,
               p.canal_venda_id, count(*) AS qtd
          FROM public.pedidos p
         WHERE p.id = ANY(COALESCE(v_ids, '{}'::integer[]))
            OR p.id IN (SELECT dp.pedido_id FROM public.demandas_pedidos dp
                         WHERE dp.demanda_id = v_demanda)
         GROUP BY 1, 2, 3
      ) t
     ORDER BY t.qtd DESC, t.marketplace_integration_id NULLS LAST
     LIMIT 1;

    SELECT m.codigo INTO v_codigo_mod
      FROM public.modalidades_logisticas m WHERE m.id = v_modalidade_id;

    SELECT COALESCE(btrim(ii.instance_name), 'Origem nao resolvida') INTO v_marketplace
      FROM public.installed_integrations ii WHERE ii.id = v_integration_id;
    v_marketplace := COALESCE(v_marketplace, 'Origem nao resolvida');

    -- 5. Cria o rascunho, ou reaproveita o desta conferencia.
    IF v_demanda IS NULL THEN
        v_codigo := COALESCE(
            NULLIF(p_escopo ->> 'codigo', ''),
            CASE WHEN v_conferencia IS NOT NULL
                 THEN 'DESPACHO-ARQ-' || v_conferencia
                 ELSE 'DESPACHO-SEL-' || to_char(now(), 'YYYYMMDDHH24MISS')
            END);

        INSERT INTO public.demandas_producao (
            demanda_id, descricao, status, tipo_demanda, canal_venda_id,
            data_entrega, observacoes, modalidade_id, modalidade_logistica,
            is_flex, escopo_despacho, origem_demanda, pedido_numero
        ) VALUES (
            v_codigo,
            COALESCE(
                NULLIF(p_nome, ''),
                NULLIF(p_escopo ->> 'nome', ''),
                format('%s / %s - %s', v_marketplace,
                       COALESCE(NULLIF(p_escopo ->> 'arquivo_nome', ''), 'Selecao'),
                       to_char(CURRENT_DATE, 'DD/MM'))),
            'RASCUNHO', 'PLATAFORMA', v_canal_id, CURRENT_DATE, p_observacoes,
            v_modalidade_id, v_codigo_mod, (v_codigo_mod = 'FLEX'),
            '{}'::jsonb, 'MANUAL', '0 pedidos'
        ) RETURNING id INTO v_demanda;
    END IF;

    INSERT INTO public.demandas_pedidos (demanda_id, pedido_id)
    SELECT v_demanda, unnest(COALESCE(v_ids, '{}'::integer[]))
    ON CONFLICT (demanda_id, pedido_id) DO NOTHING;

    SELECT array_agg(dp.pedido_id ORDER BY dp.pedido_id) INTO v_todos_ids
      FROM public.demandas_pedidos dp WHERE dp.demanda_id = v_demanda;

    IF COALESCE(array_length(v_todos_ids, 1), 0) = 0 THEN
        RAISE EXCEPTION 'Escopo vazio: nenhum pedido disponivel para lancamento'
            USING ERRCODE = 'no_data_found', DETAIL = v_conflitos::text;
    END IF;

    -- 6. Materializa pelo MESMO caminho da torre.
    --    Recalcula sobre o conjunto inteiro: o rank do miolo depende da carga
    --    total do lote, entao acrescentar linhas isoladamente daria uma ordem
    --    de producao errada.
    DELETE FROM public.demandas_item_origem
     WHERE demanda_item_id IN (
        SELECT id FROM public.itens_demanda WHERE demanda_id = v_demanda);
    DELETE FROM public.itens_demanda WHERE demanda_id = v_demanda;

    v_total_itens := public.despacho_materializar_itens(v_demanda, v_todos_ids);

    SELECT jsonb_agg(jsonb_build_object(
             'integration_id',   t.marketplace_integration_id,
             'marketplace_nome', COALESCE(btrim(ii.instance_name), 'Origem nao resolvida'),
             'modalidade_id',    t.modalidade_logistica_id,
             'modalidade_nome',  COALESCE(m.nome, 'Modalidade nao classificada'),
             'qtd_pedidos',      t.qtd) ORDER BY t.qtd DESC)
      INTO v_nos
      FROM (
        SELECT p.marketplace_integration_id, p.modalidade_logistica_id, count(*) AS qtd
          FROM public.pedidos p WHERE p.id = ANY(v_todos_ids)
         GROUP BY 1, 2
      ) t
      LEFT JOIN public.installed_integrations ii ON ii.id = t.marketplace_integration_id
      LEFT JOIN public.modalidades_logisticas  m ON m.id  = t.modalidade_logistica_id;

    UPDATE public.demandas_producao
       SET escopo_despacho = COALESCE(p_escopo, '{}'::jsonb) || jsonb_build_object(
               'origem',         COALESCE(NULLIF(p_escopo ->> 'origem', ''), 'ARQUIVO'),
               'integration_id', v_integration_id,
               'modalidade_id',  v_modalidade_id,
               'nos',            COALESCE(v_nos, '[]'::jsonb),
               'total_pedidos',  COALESCE(array_length(v_todos_ids, 1), 0),
               'montado_por',    p_user_id,
               'montado_em',     now()),
           canal_venda_id = COALESCE(canal_venda_id, v_canal_id),
           modalidade_id  = COALESCE(modalidade_id, v_modalidade_id),
           pedido_numero  = COALESCE(array_length(v_todos_ids, 1), 0)::text || ' pedidos',
           updated_at     = now()
     WHERE id = v_demanda;

    SELECT d.demanda_id INTO v_codigo
      FROM public.demandas_producao d WHERE d.id = v_demanda;

    -- despachado_em NAO e carimbado aqui: rascunho nao e despacho.
    RETURN QUERY SELECT v_demanda, v_codigo,
                        COALESCE(array_length(v_todos_ids, 1), 0),
                        COALESCE(v_total_itens, 0), v_somou, v_conflitos;
END;
$function$;

COMMENT ON FUNCTION public.despacho_lancar_pedidos(integer[], text, text, text, jsonb) IS
'Monta um RASCUNHO a partir de uma selecao explicita de pedidos (ex.: recorte de planilha). Recorta, recusa pedidos ja presentes em outro rascunho e delega a materializacao para despacho_materializar_itens — o mesmo caminho do lancamento pela torre.';

GRANT EXECUTE ON FUNCTION public.despacho_lancar_pedidos(integer[], text, text, text, jsonb)
    TO authenticated, service_role;
