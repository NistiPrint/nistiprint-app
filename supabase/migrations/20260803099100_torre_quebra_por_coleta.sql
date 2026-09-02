-- A torre agrupa pela coleta a que cada pedido pertence.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- Nivel 3 e um RECORTE ALTERNATIVO do nivel 1, nao um sub-nivel do 2. Sao duas
-- leituras do mesmo conjunto:
--
--   nivel 2  prazo do marketplace   -> urgencia (atrasado, hoje, amanha)
--   nivel 3  coleta                 -> qual caminhao leva quantos
--
-- Somar 2 com 3 conta cada pedido duas vezes. A invariante correta e:
-- soma(nivel 1) = soma(nivel 2) = soma(nivel 3) = soma(nivel 0).

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
    coleta_grupo             timestamptz,
    qtd_pedidos              integer,
    qtd_itens                integer,
    corte_em                 timestamptz,
    coleta_em                timestamptz,
    prazo_final_em           timestamptz,
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
        c.corte_em,
        c.coleta_em,
        c.prazo_final_em,
        COALESCE(i.qtd, 0)                                 AS qtd_itens
      FROM public.pedidos p
      LEFT JOIN public.installed_integrations ii
             ON ii.id = p.marketplace_integration_id
      LEFT JOIN public.modalidades_logisticas m
             ON m.id = p.modalidade_logistica_id
      -- A coleta do pedido depende de QUANDO ele foi pago: o corte e regra de
      -- pertencimento, nao prazo de producao.
      LEFT JOIN LATERAL public.coleta_do_pedido(
                    p.modalidade_logistica_id,
                    p.marketplace_integration_id,
                    COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda),
                    now()
                ) c ON true
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
    CASE
        WHEN grouping(b.modalidade_id) = 1 THEN 0
        WHEN grouping(b.bucket_prazo) = 0  THEN 2
        WHEN grouping(b.coleta_em) = 0     THEN 3
        ELSE 1
    END::smallint                                                        AS nivel,
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
    CASE WHEN grouping(b.coleta_em) = 0    THEN b.coleta_em END          AS coleta_grupo,
    count(*)::integer                                                    AS qtd_pedidos,
    COALESCE(sum(b.qtd_itens), 0)::integer                               AS qtd_itens,
    min(b.corte_em)                                                      AS corte_em,
    min(b.coleta_em)                                                     AS coleta_em,
    min(b.prazo_final_em)                                                AS prazo_final_em,
    min(b.compromisso_logistico_em)                                      AS compromisso_mais_proximo,
    COALESCE(min(b.ordem), 0)::smallint                                  AS ordem
  FROM base b
 GROUP BY GROUPING SETS (
    (b.integration_id),
    (b.integration_id, b.modalidade_id),
    (b.integration_id, b.modalidade_id, b.bucket_prazo),
    (b.integration_id, b.modalidade_id, b.coleta_em)
 )
 ORDER BY
    CASE
        WHEN grouping(b.modalidade_id) = 1 THEN 0
        WHEN grouping(b.bucket_prazo) = 0  THEN 2
        WHEN grouping(b.coleta_em) = 0     THEN 3
        ELSE 1
    END,
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
  'Quatro niveis: 0 marketplace, 1 modalidade, 2 quebra por prazo do marketplace, 3 quebra por coleta. Niveis 2 e 3 sao dois recortes do MESMO conjunto do nivel 1 — nao somar entre eles.';
