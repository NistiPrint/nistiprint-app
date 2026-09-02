-- Correção da migration 20260901190000:
-- a torre deve agrupar pela coleta, mas o conjunto de pedidos deve continuar
-- vindo da view canônica de pendentes. Nunca duplicar esse predicado aqui.

CREATE OR REPLACE FUNCTION public.despacho_arvore(p_data date DEFAULT CURRENT_DATE)
RETURNS TABLE (
    nivel smallint,
    integration_id integer,
    marketplace_nome text,
    modalidade_id integer,
    modalidade_codigo text,
    modalidade_nome text,
    tipo_prazo text,
    bucket_prazo text,
    coleta_grupo timestamptz,
    qtd_pedidos integer,
    qtd_itens integer,
    corte_em timestamptz,
    coleta_em timestamptz,
    prazo_final_em timestamptz,
    compromisso_mais_proximo timestamptz,
    ordem smallint
)
LANGUAGE sql STABLE
AS $fn$
WITH base AS (
    SELECT
        p.id,
        p.marketplace_integration_id AS integration_id,
        p.marketplace_nome,
        p.modalidade_logistica_id AS modalidade_id,
        COALESCE(p.modalidade_codigo, 'NAO_CLASSIFICADA') AS modalidade_codigo,
        COALESCE(p.modalidade_nome, 'Modalidade nao classificada') AS modalidade_nome,
        COALESCE(p.modalidade_tipo_prazo, 'FIXO') AS tipo_prazo,
        COALESCE(p.modalidade_ordem, 0)::smallint AS ordem,
        public.despacho_bucket_coleta(
            COALESCE(c.coleta_em, CASE WHEN p.modalidade_tipo_prazo = 'RELATIVO'
                                       THEN p.compromisso_logistico_em END), p_data
        ) AS bucket_prazo,
        COALESCE(c.coleta_em, CASE WHEN p.modalidade_tipo_prazo = 'RELATIVO'
                                   THEN p.compromisso_logistico_em END) AS coleta_grupo,
        p.compromisso_logistico_em,
        c.corte_em,
        c.coleta_em,
        c.prazo_final_em,
        COALESCE(i.qtd, 0) AS qtd_itens
      FROM public.vw_pedidos_pendentes_despacho p
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
), agrupada AS (
    SELECT
        CASE
            WHEN grouping(b.modalidade_id) = 1 THEN 0
            WHEN grouping(b.bucket_prazo) = 0 THEN 2
            WHEN grouping(b.coleta_grupo) = 0 THEN 3
            ELSE 1
        END::smallint AS nivel,
        b.integration_id,
        max(b.marketplace_nome)::text AS marketplace_nome,
        CASE WHEN grouping(b.modalidade_id) = 0 THEN b.modalidade_id END AS modalidade_id,
        CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.modalidade_codigo)::text END AS modalidade_codigo,
        CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.modalidade_nome)::text END AS modalidade_nome,
        CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.tipo_prazo)::text END AS tipo_prazo,
        CASE WHEN grouping(b.bucket_prazo) = 0 THEN b.bucket_prazo END AS bucket_prazo,
        CASE WHEN grouping(b.coleta_grupo) = 0 THEN b.coleta_grupo END AS coleta_grupo,
        count(*)::integer AS qtd_pedidos,
        COALESCE(sum(b.qtd_itens), 0)::integer AS qtd_itens,
        min(b.corte_em) AS corte_em,
        min(b.coleta_em) AS coleta_em,
        min(b.prazo_final_em) AS prazo_final_em,
        min(b.compromisso_logistico_em) AS compromisso_mais_proximo,
        COALESCE(min(b.ordem), 0)::smallint AS ordem
      FROM base b
     GROUP BY GROUPING SETS (
         (b.integration_id),
         (b.integration_id, b.modalidade_id),
         (b.integration_id, b.modalidade_id, b.bucket_prazo),
         (b.integration_id, b.modalidade_id, b.coleta_grupo)
     )
)
SELECT *
  FROM agrupada
 ORDER BY nivel,
          COALESCE(coleta_grupo, compromisso_mais_proximo) NULLS LAST,
          integration_id,
          ordem,
          CASE bucket_prazo
              WHEN 'atrasado' THEN 1
              WHEN 'hoje' THEN 2
              WHEN 'amanha' THEN 3
              WHEN 'depois' THEN 4
              ELSE 5
          END;
$fn$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_lote(
    p_integration_id integer,
    p_modalidade_ids integer[] DEFAULT NULL,
    p_horizonte text[] DEFAULT ARRAY['atrasado', 'hoje'],
    p_data date DEFAULT CURRENT_DATE
)
RETURNS SETOF integer
LANGUAGE sql STABLE
SET search_path TO public, pg_temp
AS $fn$
    SELECT p.id
      FROM public.vw_pedidos_pendentes_despacho p
      LEFT JOIN LATERAL public.coleta_do_pedido(
          p.modalidade_logistica_id,
          p.marketplace_integration_id,
          COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda),
          now()
      ) c ON true
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND (
           p.modalidade_logistica_id = ANY (p_modalidade_ids)
           OR (p.modalidade_logistica_id IS NULL AND p_modalidade_ids IS NULL)
       )
       AND public.despacho_bucket_coleta(
           COALESCE(c.coleta_em, CASE WHEN p.modalidade_tipo_prazo = 'RELATIVO'
                                      THEN p.compromisso_logistico_em END), p_data
       ) = ANY (p_horizonte)
     ORDER BY COALESCE(c.coleta_em, p.compromisso_logistico_em) NULLS LAST, p.id;
$fn$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_pedidos(
    p_integration_id integer,
    p_modalidade_id integer,
    p_horizonte text[] DEFAULT ARRAY['atrasado', 'hoje'],
    p_data date DEFAULT CURRENT_DATE
)
RETURNS SETOF integer
LANGUAGE sql STABLE
AS $fn$
    SELECT p.id
      FROM public.vw_pedidos_pendentes_despacho p
      LEFT JOIN LATERAL public.coleta_do_pedido(
          p.modalidade_logistica_id,
          p.marketplace_integration_id,
          COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda),
          now()
      ) c ON true
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id IS NOT DISTINCT FROM p_modalidade_id
       AND public.despacho_bucket_coleta(
           COALESCE(c.coleta_em, CASE WHEN p.modalidade_tipo_prazo = 'RELATIVO'
                                      THEN p.compromisso_logistico_em END), p_data
       ) = ANY (p_horizonte)
     ORDER BY COALESCE(c.coleta_em, p.compromisso_logistico_em) NULLS LAST, p.id;
$fn$;

COMMENT ON FUNCTION public.despacho_arvore(date) IS
  'Arvore usa exclusivamente vw_pedidos_pendentes_despacho para o filtro e data da coleta para os buckets.';