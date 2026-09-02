-- A torre e o escopo do lote devem usar o mesmo eixo operacional:
-- a data em que a transportadora coleta, e nao o prazo de envio do pedido.
-- O prazo de envio continua disponivel no detalhe do pedido, mas nao decide
-- em qual aba o lote aparece.

CREATE OR REPLACE FUNCTION public.despacho_bucket_coleta(
    p_coleta_em timestamptz,
    p_data date DEFAULT (now() AT TIME ZONE 'America/Sao_Paulo')::date
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$
    SELECT CASE
             WHEN p_coleta_em IS NULL THEN 'sem_prazo'
             WHEN (p_coleta_em AT TIME ZONE 'America/Sao_Paulo')::date < p_data THEN 'atrasado'
             WHEN (p_coleta_em AT TIME ZONE 'America/Sao_Paulo')::date = p_data THEN 'hoje'
             WHEN (p_coleta_em AT TIME ZONE 'America/Sao_Paulo')::date = p_data + 1 THEN 'amanha'
             ELSE 'depois'
           END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_arvore(p_data date DEFAULT CURRENT_DATE)
RETURNS TABLE (
    nivel smallint, integration_id integer, marketplace_nome text,
    modalidade_id integer, modalidade_codigo text, modalidade_nome text,
    tipo_prazo text, bucket_prazo text, coleta_grupo timestamptz,
    qtd_pedidos integer, qtd_itens integer, corte_em timestamptz,
    coleta_em timestamptz, prazo_final_em timestamptz,
    compromisso_mais_proximo timestamptz, ordem smallint
)
LANGUAGE sql STABLE
AS $fn$
WITH base AS (
    SELECT p.id, p.marketplace_integration_id AS integration_id,
           COALESCE(ii.instance_name, 'Origem nao resolvida') AS marketplace_nome,
           p.modalidade_logistica_id AS modalidade_id,
           COALESCE(m.codigo, 'NAO_CLASSIFICADA') AS modalidade_codigo,
           COALESCE(m.nome, 'Modalidade nao classificada') AS modalidade_nome,
           COALESCE(m.tipo_prazo, 'FIXO') AS tipo_prazo,
           COALESCE(m.ordem_exibicao, 0)::smallint AS ordem,
           public.despacho_bucket_coleta(
               COALESCE(c.coleta_em, CASE WHEN m.tipo_prazo = 'RELATIVO'
                                          THEN p.compromisso_logistico_em END), p_data
           ) AS bucket_prazo,
           COALESCE(c.coleta_em, CASE WHEN m.tipo_prazo = 'RELATIVO'
                                      THEN p.compromisso_logistico_em END) AS coleta_grupo,
           p.compromisso_logistico_em, c.corte_em, c.coleta_em, c.prazo_final_em,
           COALESCE(i.qtd, 0) AS qtd_itens
      FROM public.pedidos p
      LEFT JOIN public.installed_integrations ii ON ii.id = p.marketplace_integration_id
      LEFT JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
      LEFT JOIN LATERAL public.coleta_do_pedido(
          p.modalidade_logistica_id, p.marketplace_integration_id,
          COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda), now()
      ) c ON true
      LEFT JOIN LATERAL (
          SELECT round(sum(ip.quantidade))::integer AS qtd
            FROM public.itens_pedido ip WHERE ip.pedido_id = p.id
      ) i ON true
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
       AND NOT EXISTS (
           SELECT 1 FROM public.demandas_pedidos dp
           JOIN public.demandas_producao d ON d.id = dp.demanda_id
           WHERE dp.pedido_id = p.id
             AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
       )
)
SELECT CASE WHEN grouping(b.modalidade_id) = 1 THEN 0
            WHEN grouping(b.bucket_prazo) = 0 THEN 2
            WHEN grouping(b.coleta_grupo) = 0 THEN 3 ELSE 1 END::smallint,
       b.integration_id, max(b.marketplace_nome),
       CASE WHEN grouping(b.modalidade_id) = 0 THEN b.modalidade_id END,
       CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.modalidade_codigo)::text END,
       CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.modalidade_nome)::text END,
       CASE WHEN grouping(b.modalidade_id) = 0 THEN max(b.tipo_prazo)::text END,
       CASE WHEN grouping(b.bucket_prazo) = 0 THEN b.bucket_prazo END,
       CASE WHEN grouping(b.coleta_grupo) = 0 THEN b.coleta_grupo END,
       count(*)::integer, COALESCE(sum(b.qtd_itens), 0)::integer,
       min(b.corte_em), min(b.coleta_em), min(b.prazo_final_em),
       min(b.compromisso_logistico_em), COALESCE(min(b.ordem), 0)::smallint
  FROM base b
 GROUP BY GROUPING SETS (
       (b.integration_id), (b.integration_id, b.modalidade_id),
       (b.integration_id, b.modalidade_id, b.bucket_prazo),
       (b.integration_id, b.modalidade_id, b.coleta_grupo)
 )
 ORDER BY CASE WHEN grouping(b.modalidade_id) = 1 THEN 0
               WHEN grouping(b.bucket_prazo) = 0 THEN 2
               WHEN grouping(b.coleta_grupo) = 0 THEN 3 ELSE 1 END,
          COALESCE(min(b.coleta_grupo), min(b.compromisso_logistico_em)) NULLS LAST,
          b.integration_id, COALESCE(min(b.ordem), 0);
$fn$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_lote(
    p_integration_id integer, p_modalidade_ids integer[] DEFAULT NULL,
    p_horizonte text[] DEFAULT ARRAY['atrasado', 'hoje'],
    p_data date DEFAULT CURRENT_DATE
) RETURNS SETOF integer
LANGUAGE sql STABLE
AS $fn$
    SELECT p.id
      FROM public.pedidos p
      LEFT JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
      LEFT JOIN LATERAL public.coleta_do_pedido(
          p.modalidade_logistica_id, p.marketplace_integration_id,
          COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda), now()
      ) c ON true
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
       AND p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND (p_modalidade_ids IS NULL OR cardinality(p_modalidade_ids) = 0
            OR p.modalidade_logistica_id = ANY(p_modalidade_ids)
            OR (p.modalidade_logistica_id IS NULL AND NULL = ANY(p_modalidade_ids)))
       AND public.despacho_bucket_coleta(
           COALESCE(c.coleta_em, CASE WHEN m.tipo_prazo = 'RELATIVO'
                                      THEN p.compromisso_logistico_em END), p_data
       ) = ANY(COALESCE(p_horizonte, ARRAY['atrasado', 'hoje']))
     ORDER BY COALESCE(c.coleta_em, p.compromisso_logistico_em) NULLS LAST, p.id;
$fn$;

COMMENT ON FUNCTION public.despacho_bucket_coleta(timestamptz, date) IS
  'Bucket operacional da torre: data da coleta no fuso de Sao Paulo.';

CREATE OR REPLACE FUNCTION public.despacho_escopo_pedidos(
    p_integration_id integer, p_modalidade_id integer,
    p_horizonte text[] DEFAULT ARRAY['atrasado', 'hoje'],
    p_data date DEFAULT CURRENT_DATE
) RETURNS SETOF integer
LANGUAGE sql STABLE
AS $fn$
    SELECT p.id
      FROM public.pedidos p
      LEFT JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
      LEFT JOIN LATERAL public.coleta_do_pedido(
          p.modalidade_logistica_id, p.marketplace_integration_id,
          COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda), now()
      ) c ON true
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
       AND p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id IS NOT DISTINCT FROM p_modalidade_id
       AND public.despacho_bucket_coleta(
           COALESCE(c.coleta_em, CASE WHEN m.tipo_prazo = 'RELATIVO'
                                      THEN p.compromisso_logistico_em END), p_data
       ) = ANY(COALESCE(p_horizonte, ARRAY['atrasado', 'hoje']))
     ORDER BY COALESCE(c.coleta_em, p.compromisso_logistico_em) NULLS LAST, p.id;
$fn$;