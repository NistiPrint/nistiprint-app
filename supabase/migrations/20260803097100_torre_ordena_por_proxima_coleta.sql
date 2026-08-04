-- A torre passa a ordenar e exibir pela proxima coleta, e ignora pedido que ja
-- esta em demanda publicada.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## Coleta e corte tem papeis diferentes
--
--   corte    ate quando o lote precisa estar pronto. Define QUEM entra na
--            coleta — e o saneamento que o operador nao deveria ter que fazer
--            na mao.
--   coleta   quando a transportadora passa. E o processo fisico, e e assim que
--            a operacao pensa no lote: "o caminhao das 17h".
--
-- Por isso a ordenacao e a leitura principal do card usam a coleta, e o corte
-- aparece como "pronto ate". Ordenar pelo corte colocaria na frente um lote que
-- fecha antes mas sai depois.
--
-- Modalidade RELATIVO nao tem coleta recorrente: cai no relogio proprio do
-- pedido (`compromisso_logistico_em`), via COALESCE na ordenacao.
--
-- ## Pedido ja em demanda
--
-- Criterio: fora da torre se pertence a demanda com status diferente de
-- RASCUNHO e nao cancelada. Rascunho continua aparecendo — mesmo criterio da
-- esteira Turbo. A escolha assume o risco de alguem lancar duas vezes o mesmo
-- pedido em favor de nunca esconder pedido por causa de um rascunho que
-- ninguem terminou. Some silenciosamente e pior que aparecer duas vezes.

DROP FUNCTION IF EXISTS public.despacho_arvore(date);

CREATE FUNCTION public.despacho_arvore(
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
    corte_em                 timestamptz,
    coleta_em                timestamptz,
    compromisso_mais_proximo timestamptz,
    ordem                    smallint
)
LANGUAGE sql
STABLE
AS $fn$
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
            WHEN p.data_limite_envio IS NULL               THEN 'sem_prazo'
            WHEN (p.data_limite_envio)::date <  p_data     THEN 'atrasado'
            WHEN (p.data_limite_envio)::date =  p_data     THEN 'hoje'
            WHEN (p.data_limite_envio)::date =  p_data + 1 THEN 'amanha'
            ELSE 'depois'
        END                                                AS bucket_prazo,
        p.compromisso_logistico_em,
        j.corte_em,
        j.coleta_em,
        COALESCE(i.qtd, 0)                                 AS qtd_itens
      FROM public.pedidos p
      LEFT JOIN public.installed_integrations ii
             ON ii.id = p.marketplace_integration_id
      LEFT JOIN public.modalidades_logisticas m
             ON m.id = p.modalidade_logistica_id
      LEFT JOIN LATERAL public.proxima_janela_logistica(
                    p.modalidade_logistica_id, p.marketplace_integration_id, now()
                ) j ON true
      LEFT JOIN LATERAL (
            SELECT round(sum(ip.quantidade))::integer AS qtd
              FROM public.itens_pedido ip
             WHERE ip.pedido_id = p.id
      ) i ON true
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
       AND NOT EXISTS (
             SELECT 1
               FROM public.demandas_pedidos dp
               JOIN public.demandas_producao d ON d.id = dp.demanda_id
              WHERE dp.pedido_id = p.id
                AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
       )
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
    min(b.corte_em)                                                      AS corte_em,
    min(b.coleta_em)                                                     AS coleta_em,
    min(b.compromisso_logistico_em)                                      AS compromisso_mais_proximo,
    COALESCE(min(b.ordem), 0)::smallint                                  AS ordem
  FROM base b
 GROUP BY GROUPING SETS (
    (b.integration_id),
    (b.integration_id, b.modalidade_id),
    (b.integration_id, b.modalidade_id, b.bucket_prazo)
 )
 ORDER BY
    (2 - grouping(b.modalidade_id) - grouping(b.bucket_prazo)),
    -- Ordena pela coleta: e o processo fisico, o caminhao que vai passar.
    -- Turbo nao tem coleta recorrente, entao cai no relogio proprio do pedido.
    COALESCE(min(b.coleta_em), min(b.compromisso_logistico_em)) NULLS LAST,
    b.integration_id,
    COALESCE(min(b.ordem), 0),
    CASE
        WHEN grouping(b.bucket_prazo) = 1 THEN 0
        WHEN b.bucket_prazo = 'atrasado'  THEN 1
        WHEN b.bucket_prazo = 'hoje'      THEN 2
        WHEN b.bucket_prazo = 'amanha'    THEN 3
        WHEN b.bucket_prazo = 'depois'    THEN 4
        ELSE 5
    END;
$fn$;

COMMENT ON FUNCTION public.despacho_arvore(date) IS
  'Totalizadores em tres niveis, ordenados pela proxima coleta. corte_em e coleta_em sao calculados na leitura e sempre futuros; compromisso_mais_proximo so tem valor para modalidade RELATIVO.';

-- --------------------------------------------------------------------------
-- Mesmo predicado de pendencia, palavra por palavra.
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
AS $fn$
    SELECT p.id
      FROM public.pedidos p
      LEFT JOIN public.modalidades_logisticas m
             ON m.id = p.modalidade_logistica_id
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
       AND NOT EXISTS (
             SELECT 1
               FROM public.demandas_pedidos dp
               JOIN public.demandas_producao d ON d.id = dp.demanda_id
              WHERE dp.pedido_id = p.id
                AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
       )
       AND p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id    IS NOT DISTINCT FROM p_modalidade_id
       AND CASE
             WHEN p.data_limite_envio IS NULL               THEN 'sem_prazo'
             WHEN (p.data_limite_envio)::date <  p_data     THEN 'atrasado'
             WHEN (p.data_limite_envio)::date =  p_data     THEN 'hoje'
             WHEN (p.data_limite_envio)::date =  p_data + 1 THEN 'amanha'
             ELSE 'depois'
           END = ANY (p_horizonte)
     -- Dentro do lote, o mais urgente primeiro: todos compartilham a mesma
     -- coleta, entao o que desempata e o prazo do marketplace.
     ORDER BY p.data_limite_envio NULLS LAST, p.id;
$fn$;

COMMENT ON FUNCTION public.despacho_escopo_pedidos(integer, integer, text[], date) IS
  'Predicado de pendencia identico ao de despacho_arvore, incluindo a exclusao de pedido ja em demanda publicada.';
