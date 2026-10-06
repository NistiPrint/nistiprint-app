-- Leituras de despacho: mesma pendencia e mesmo prazo, menos consultas.
-- A view existente continua sendo a autoridade (somente Em Andamento).

CREATE OR REPLACE FUNCTION public.despacho_coletas_em_lote(
    p_pedido_ids integer[], p_agora timestamptz DEFAULT now()
)
RETURNS TABLE(pedido_id integer, corte_em timestamptz, coleta_em timestamptz, prazo_final_em timestamptz)
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH pedidos_base AS MATERIALIZED (
    SELECT p.id, p.modalidade_logistica_id AS modalidade_id,
           p.marketplace_integration_id AS integration_id,
           COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda) AS referencia,
           CASE WHEN lower(p.marketplace_module_id) = 'mercadolivre'
                      AND p.data_limite_envio > p_agora
                THEN (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date END AS dia_sla
      FROM public.pedidos p
      JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id AND m.tipo_prazo = 'FIXO'
     WHERE p.id = ANY(p_pedido_ids) AND p.marketplace_integration_id IS NOT NULL
), calendarios AS MATERIALIZED (
    SELECT DISTINCT modalidade_id, integration_id, NULL::date AS dia_sla,
           (p_agora AT TIME ZONE 'America/Sao_Paulo')::date - 1 AS inicio,
           (p_agora AT TIME ZONE 'America/Sao_Paulo')::date + 21 AS fim
      FROM pedidos_base
    UNION
    SELECT DISTINCT modalidade_id, integration_id, dia_sla, dia_sla - 14, dia_sla
      FROM pedidos_base WHERE dia_sla IS NOT NULL
), janelas AS MATERIALIZED (
    SELECT c.modalidade_id, c.integration_id, c.dia_sla, j.*
      FROM calendarios c
      CROSS JOIN LATERAL public.logistica_lotes(c.modalidade_id, c.integration_id, c.inicio, c.fim) j
)
SELECT p.id, COALESCE(sla.corte_em, proxima.corte_em),
       COALESCE(sla.coleta_em, proxima.coleta_em), COALESCE(sla.prazo_final_em, proxima.prazo_final_em)
  FROM pedidos_base p
  LEFT JOIN LATERAL (
      SELECT j.corte_em, j.coleta_em, j.prazo_final_em FROM janelas j
       WHERE p.dia_sla IS NOT NULL AND j.dia_sla = p.dia_sla
         AND j.modalidade_id = p.modalidade_id AND j.integration_id = p.integration_id
         AND j.corte_em >= GREATEST(COALESCE(p.referencia, p_agora), p_agora)
         AND j.prazo_final_em > p_agora
         AND j.prazo_final_em < ((p.dia_sla + 1)::timestamp AT TIME ZONE 'America/Sao_Paulo')
       ORDER BY j.prazo_final_em DESC, j.coleta_em DESC LIMIT 1
  ) sla ON true
  LEFT JOIN LATERAL (
      SELECT j.corte_em, j.coleta_em, j.prazo_final_em FROM janelas j
       WHERE sla.coleta_em IS NULL AND j.dia_sla IS NULL
         AND j.modalidade_id = p.modalidade_id AND j.integration_id = p.integration_id
         AND j.corte_em >= COALESCE(p.referencia, p_agora) AND j.prazo_final_em > p_agora
       ORDER BY j.corte_em, j.coleta_em LIMIT 1
  ) proxima ON true;
$$;

-- POST RPC evita URLs com milhares de IDs e o teto de linhas do PostgREST.
CREATE OR REPLACE FUNCTION public.despacho_ler_pedidos(p_pedido_ids integer[])
RETURNS jsonb LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'id', p.id, 'numero_pedido', p.numero_pedido, 'codigo_pedido_externo', p.codigo_pedido_externo,
        'cliente_nome', p.cliente_nome, 'total_pedido', p.total_pedido, 'data_venda', p.data_venda,
        'data_limite_envio', p.data_limite_envio, 'compromisso_logistico_em', p.compromisso_logistico_em,
        'metodo_envio_chave', p.metodo_envio_chave, 'metodo_envio_rotulo', p.metodo_envio_rotulo,
        'modalidade_logistica_id', p.modalidade_logistica_id, 'pack_id', p.pack_id,
        'marketplace_order_id', p.marketplace_order_id, 'marketplace_module_id', p.marketplace_module_id,
        'marketplace_integration_id', p.marketplace_integration_id,
        'erp_integration_id', p.erp_integration_id, 'erp_store_id', p.erp_store_id,
        'erp_order_id', p.erp_order_id, 'erp_order_number', p.erp_order_number
    ) ORDER BY p.data_limite_envio NULLS LAST, p.id), '[]'::jsonb)
    FROM public.pedidos p WHERE p.id = ANY(p_pedido_ids);
$$;

-- Contexto da torre em uma ida ao banco; as RPCs antigas continuam disponiveis.
CREATE OR REPLACE FUNCTION public.despacho_arvore_contexto(p_data date)
RETURNS jsonb LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH arvore AS MATERIALIZED (SELECT * FROM public.despacho_arvore(p_data)),
integracoes AS (SELECT DISTINCT integration_id FROM arvore WHERE integration_id IS NOT NULL),
janelas AS (
    SELECT a.integration_id, a.modalidade_id, jsonb_agg(to_jsonb(j) ORDER BY j.coleta_em) AS dados
      FROM arvore a CROSS JOIN LATERAL public.janelas_logisticas(
          a.modalidade_id, a.integration_id, (a.coleta_em AT TIME ZONE 'America/Sao_Paulo')::date
      ) j WHERE a.nivel = 1 AND a.modalidade_id IS NOT NULL AND a.coleta_em IS NOT NULL
     GROUP BY a.integration_id, a.modalidade_id
)
SELECT jsonb_build_object(
    'rows', COALESCE((SELECT jsonb_agg(to_jsonb(a)) FROM arvore a), '[]'::jsonb),
    'catalogo', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', m.id, 'entrega_rapida', m.entrega_rapida)) FROM public.modalidades_logisticas m), '[]'::jsonb),
    'integracoes', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', i.id, 'module_id', i.module_id)) FROM public.installed_integrations i JOIN integracoes ids ON ids.integration_id = i.id), '[]'::jsonb),
    'composicao', COALESCE((SELECT jsonb_agg(to_jsonb(c)) FROM public.despacho_composicao_situacao(p_data) c), '[]'::jsonb),
    'lotes', COALESCE((SELECT jsonb_agg(to_jsonb(l) || jsonb_build_object('integration_id', ids.integration_id)) FROM integracoes ids CROSS JOIN LATERAL public.despacho_lotes(ids.integration_id) l), '[]'::jsonb),
    'rascunhos', COALESCE((SELECT jsonb_agg(to_jsonb(r)) FROM public.despacho_rascunhos_abertos(p_data) r), '[]'::jsonb),
    'janelas', COALESCE((SELECT jsonb_agg(to_jsonb(j)) FROM janelas j), '[]'::jsonb)
);
$$;

-- Contexto de escopo usa uma selecao unica para contadores e lista.
CREATE OR REPLACE FUNCTION public.despacho_escopo_contexto(
    p_integration_id integer, p_modalidade_ids integer[], p_horizonte text[], p_data date
)
RETURNS jsonb LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH base AS MATERIALIZED (
    SELECT p.id, public.despacho_bucket_prazo(p.data_limite_envio, p_data) AS bucket
      FROM public.vw_pedidos_pendentes_despacho p
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND (p.modalidade_logistica_id = ANY(p_modalidade_ids)
            OR (p.modalidade_logistica_id IS NULL AND p_modalidade_ids IS NULL))
), selecionados AS (SELECT id FROM base WHERE bucket = ANY(p_horizonte)),
ids AS (SELECT COALESCE(array_agg(id ORDER BY id), '{}'::integer[]) AS dados FROM selecionados),
buckets AS (SELECT bucket, count(*) AS qtd FROM base GROUP BY bucket)
SELECT jsonb_build_object(
    'pedido_ids', ids.dados,
    'pedidos', public.despacho_ler_pedidos(ids.dados),
    'pacotes', COALESCE((SELECT jsonb_agg(to_jsonb(p)) FROM public.pedidos_pacotes(ids.dados) p), '[]'::jsonb),
    'buckets', COALESCE((SELECT jsonb_object_agg(bucket, qtd) FROM buckets), '{}'::jsonb),
    'total_no', (SELECT count(*) FROM base),
    'contas', COALESCE((SELECT jsonb_object_agg(i.id::text, i.instance_name) FROM public.installed_integrations i
        WHERE i.id IN (SELECT p.erp_integration_id FROM public.pedidos p WHERE p.id = ANY(ids.dados))), '{}'::jsonb)
) FROM ids;
$$;

-- Os payloads contem pedidos e contas de ERP: somente o backend autenticado.
REVOKE ALL ON FUNCTION public.despacho_coletas_em_lote(integer[],timestamptz),
    public.despacho_ler_pedidos(integer[]),
    public.despacho_arvore_contexto(date), public.despacho_escopo_contexto(integer,integer[],text[],date)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_coletas_em_lote(integer[],timestamptz),
    public.despacho_ler_pedidos(integer[]),
    public.despacho_arvore_contexto(date), public.despacho_escopo_contexto(integer,integer[],text[],date)
    TO service_role;

CREATE OR REPLACE FUNCTION public.despacho_arvore(p_data date DEFAULT CURRENT_DATE)
 RETURNS TABLE(nivel smallint, integration_id integer, marketplace_nome text, modalidade_id integer, modalidade_codigo text, modalidade_nome text, tipo_prazo text, bucket_prazo text, coleta_grupo timestamp with time zone, qtd_pedidos integer, qtd_itens integer, corte_em timestamp with time zone, coleta_em timestamp with time zone, prazo_final_em timestamp with time zone, compromisso_mais_proximo timestamp with time zone, ordem smallint)
 LANGUAGE sql
 STABLE
AS $function$
WITH pendentes AS MATERIALIZED (SELECT * FROM public.vw_pedidos_pendentes_despacho),
itens AS MATERIALIZED (
    SELECT ip.pedido_id, round(sum(ip.quantidade))::integer AS qtd
      FROM public.itens_pedido ip JOIN pendentes p ON p.id = ip.pedido_id
     GROUP BY ip.pedido_id
),
coletas AS MATERIALIZED (
    SELECT * FROM public.despacho_coletas_em_lote((SELECT array_agg(id) FROM pendentes), now())
), base AS (
    SELECT
        p.id,
        p.marketplace_integration_id AS integration_id,
        p.marketplace_nome,
        p.modalidade_logistica_id AS modalidade_id,
        COALESCE(p.modalidade_codigo, 'NAO_CLASSIFICADA') AS modalidade_codigo,
        COALESCE(p.modalidade_nome, 'Modalidade nao classificada') AS modalidade_nome,
        COALESCE(p.modalidade_tipo_prazo, 'FIXO') AS tipo_prazo,
        COALESCE(p.modalidade_ordem, 0)::smallint AS ordem,
        public.despacho_bucket_prazo(p.data_limite_envio, p_data) AS bucket_prazo,
        COALESCE(c.coleta_em, CASE WHEN p.modalidade_tipo_prazo = 'RELATIVO'
                                   THEN p.compromisso_logistico_em END) AS coleta_grupo,
        p.compromisso_logistico_em,
        c.corte_em,
        c.coleta_em,
        c.prazo_final_em,
        COALESCE(i.qtd, 0) AS qtd_itens
      FROM pendentes p
      LEFT JOIN coletas c ON c.pedido_id = p.id
      LEFT JOIN itens i ON i.pedido_id = p.id
), agrupada AS (
    SELECT
        CASE
            WHEN grouping(b.modalidade_id) = 1 THEN 0
            WHEN grouping(b.bucket_prazo) = 0 AND grouping(b.coleta_grupo) = 0 THEN 4
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
         (b.integration_id, b.modalidade_id, b.coleta_grupo),
         (b.integration_id, b.modalidade_id, b.bucket_prazo, b.coleta_grupo)
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
$function$;


CREATE OR REPLACE FUNCTION public.despacho_escopo_lote(
    p_integration_id integer, p_modalidade_ids integer[] DEFAULT NULL,
    p_horizonte text[] DEFAULT ARRAY['atrasado','hoje'], p_data date DEFAULT CURRENT_DATE
) RETURNS SETOF integer LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH selecionados AS MATERIALIZED (
    SELECT p.id, p.compromisso_logistico_em FROM public.vw_pedidos_pendentes_despacho p
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND (p.modalidade_logistica_id = ANY(p_modalidade_ids)
            OR (p.modalidade_logistica_id IS NULL AND p_modalidade_ids IS NULL))
       AND public.despacho_bucket_prazo(p.data_limite_envio, p_data) = ANY(p_horizonte)
), coletas AS MATERIALIZED (
    SELECT * FROM public.despacho_coletas_em_lote((SELECT array_agg(id) FROM selecionados), now())
)
SELECT p.id FROM selecionados p LEFT JOIN coletas c ON c.pedido_id = p.id
 ORDER BY COALESCE(c.coleta_em, p.compromisso_logistico_em) NULLS LAST, p.id;
$$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_pedidos(
    p_integration_id integer, p_modalidade_id integer,
    p_horizonte text[] DEFAULT ARRAY['atrasado','hoje'], p_data date DEFAULT CURRENT_DATE
) RETURNS SETOF integer LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
    SELECT * FROM public.despacho_escopo_lote(p_integration_id,
        CASE WHEN p_modalidade_id IS NULL THEN NULL ELSE ARRAY[p_modalidade_id] END,
        p_horizonte, p_data);
$$;
GRANT EXECUTE ON FUNCTION public.despacho_coletas_em_lote(integer[],timestamptz) TO authenticated;
