-- Arvore de totalizadores da torre de despacho.
-- Contrato: docs/specs/02-domains/despacho/spec.md, secao "Arvore de totalizadores"
--
-- Tres niveis (marketplace, modalidade, prazo) em UMA chamada, via GROUPING
-- SETS. A invariante "soma dos filhos igual ao pai" e garantida pela propria
-- agregacao, nao por soma no cliente. Se a API fizer tres consultas, a
-- invariante vira acordo de cavalheiros e quebra na primeira corrida.
--
-- qtd_pedidos e o numero de conferencia contra o painel do marketplace, porque
-- e a unidade que a tela da origem exibe. qtd_itens e carga de producao e nunca
-- deve ser apresentado como numero comparavel com a origem.
--
-- Todo pedido aberto pertence a exatamente um caminho, inclusive:
--   - sem marketplace resolvido  -> integration_id NULL, "Origem nao resolvida"
--   - sem modalidade classificada-> modalidade_id NULL, "Modalidade nao classificada"
--   - sem data_limite_envio      -> bucket "sem_prazo"
-- Nenhum desses casos bloqueia lancamento. Ver "degradar, nao bloquear".

CREATE OR REPLACE FUNCTION public.despacho_arvore(
    p_data date DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    nivel                    smallint,
    integration_id           integer,
    marketplace_nome         text,
    modalidade_id            integer,
    modalidade_codigo        text,
    modalidade_nome          text,
    tipo_prazo               text,
    bucket_prazo             text,
    qtd_pedidos              integer,
    qtd_itens                integer,
    compromisso_mais_proximo timestamptz,
    ordem                    smallint
)
LANGUAGE sql
STABLE
AS $$
WITH base AS (
    SELECT
        p.id,
        p.marketplace_integration_id                       AS integration_id,
        COALESCE(ii.instance_name, 'Origem nao resolvida') AS marketplace_nome,
        p.modalidade_logistica_id                          AS modalidade_id,
        COALESCE(m.codigo, 'NAO_CLASSIFICADA')             AS modalidade_codigo,
        COALESCE(m.nome, 'Modalidade nao classificada')    AS modalidade_nome,
        COALESCE(m.tipo_prazo, 'FIXO')                     AS tipo_prazo,
        COALESCE(m.ordem_exibicao, 0)::smallint            AS ordem,
        CASE
            WHEN p.data_limite_envio IS NULL                             THEN 'sem_prazo'
            WHEN (p.data_limite_envio)::date <  p_data                   THEN 'atrasado'
            WHEN (p.data_limite_envio)::date =  p_data                   THEN 'hoje'
            WHEN (p.data_limite_envio)::date =  p_data + 1               THEN 'amanha'
            ELSE 'depois'
        END                                                AS bucket_prazo,
        p.compromisso_logistico_em,
        COALESCE(i.qtd, 0)                                 AS qtd_itens
      FROM public.pedidos p
      LEFT JOIN public.installed_integrations ii
             ON ii.id = p.marketplace_integration_id
      LEFT JOIN public.modalidades_logisticas m
             ON m.id = p.modalidade_logistica_id
      LEFT JOIN LATERAL (
            -- itens_pedido.quantidade e numeric(10,4); arredondar antes de
            -- expor, para o contador nunca aparecer truncado em tela.
            SELECT round(sum(ip.quantidade))::integer AS qtd
              FROM public.itens_pedido ip
             WHERE ip.pedido_id = p.id
      ) i ON true
     WHERE p.despachado_em IS NULL
)
SELECT
    (2 - grouping(b.modalidade_id) - grouping(b.bucket_prazo))::smallint AS nivel,
    b.integration_id,
    max(b.marketplace_nome)::text                                        AS marketplace_nome,
    CASE WHEN grouping(b.modalidade_id) = 0 THEN b.modalidade_id END     AS modalidade_id,
    CASE WHEN grouping(b.modalidade_id) = 0
         THEN max(b.modalidade_codigo)::text END                         AS modalidade_codigo,
    CASE WHEN grouping(b.modalidade_id) = 0
         THEN max(b.modalidade_nome)::text END                           AS modalidade_nome,
    CASE WHEN grouping(b.modalidade_id) = 0
         THEN max(b.tipo_prazo)::text END                                AS tipo_prazo,
    CASE WHEN grouping(b.bucket_prazo) = 0 THEN b.bucket_prazo END       AS bucket_prazo,
    count(*)::integer                                                    AS qtd_pedidos,
    COALESCE(sum(b.qtd_itens), 0)::integer                               AS qtd_itens,
    min(b.compromisso_logistico_em)                                      AS compromisso_mais_proximo,
    COALESCE(min(b.ordem), 0)::smallint                                  AS ordem
  FROM base b
 GROUP BY GROUPING SETS (
    (b.integration_id),
    (b.integration_id, b.modalidade_id),
    (b.integration_id, b.modalidade_id, b.bucket_prazo)
 )
 ORDER BY
    -- Nivel 1 primeiro para o cliente montar a arvore em uma passada.
    (2 - grouping(b.modalidade_id) - grouping(b.bucket_prazo)),
    min(b.compromisso_logistico_em) NULLS LAST,
    b.integration_id,
    COALESCE(min(b.ordem), 0),
    -- atrasado sempre primeiro no seu nivel; sem_prazo por ultimo.
    CASE
        WHEN grouping(b.bucket_prazo) = 1 THEN 0
        WHEN b.bucket_prazo = 'atrasado'  THEN 1
        WHEN b.bucket_prazo = 'hoje'      THEN 2
        WHEN b.bucket_prazo = 'amanha'    THEN 3
        WHEN b.bucket_prazo = 'depois'    THEN 4
        ELSE 5
    END;
$$;

COMMENT ON FUNCTION public.despacho_arvore(date) IS
  'Tres niveis de totalizadores em uma chamada. nivel 0 = marketplace, 1 = modalidade, 2 = prazo. qtd_pedidos e a unidade de conferencia contra o painel da origem; qtd_itens e carga de producao.';

-- --------------------------------------------------------------------------
-- Escopo: os pedidos de um no, para o lancamento
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.despacho_escopo_pedidos(
    p_integration_id integer,
    p_modalidade_id  integer,
    p_horizonte      text[] DEFAULT ARRAY['atrasado', 'hoje'],
    p_data           date DEFAULT CURRENT_DATE
)
RETURNS SETOF integer
LANGUAGE sql
STABLE
AS $$
    SELECT p.id
      FROM public.pedidos p
     WHERE p.despachado_em IS NULL
       AND p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id    IS NOT DISTINCT FROM p_modalidade_id
       AND CASE
             WHEN p.data_limite_envio IS NULL               THEN 'sem_prazo'
             WHEN (p.data_limite_envio)::date <  p_data     THEN 'atrasado'
             WHEN (p.data_limite_envio)::date =  p_data     THEN 'hoje'
             WHEN (p.data_limite_envio)::date =  p_data + 1 THEN 'amanha'
             ELSE 'depois'
           END = ANY (p_horizonte)
     ORDER BY p.compromisso_logistico_em NULLS FIRST, p.id;
$$;

COMMENT ON FUNCTION public.despacho_escopo_pedidos(integer, integer, text[], date) IS
  'IS NOT DISTINCT FROM: NULL casa com NULL, para que os nos "Origem nao resolvida" e "Modalidade nao classificada" sejam lancaveis como qualquer outro.';
