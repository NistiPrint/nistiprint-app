-- Prazo oficial tem prioridade. Sem prazo, o pedido pertence a data da
-- proxima coleta disponivel, usando a mesma agenda da torre.
-- Retira apenas estimativas identificaveis; prazos oficiais e conferidos
-- permanecem preservados. A origem e o valor anterior ficam na auditoria.
CREATE OR REPLACE FUNCTION public.shopee_preservar_prazo_painel()
RETURNS trigger LANGUAGE plpgsql SET search_path TO public, pg_temp AS $$
DECLARE confirmado timestamptz; descartado timestamptz;
BEGIN
    IF NEW.marketplace_module_id = 'shopee' THEN
        SELECT CASE WHEN s.logistics->>'dispatch_deadline_source' = 'shopee.seller_panel.confirmed'
                    THEN NULLIF(s.logistics->>'deadline', '')::timestamptz END,
               CASE WHEN s.logistics->'deadline_reconciliation'->>'discarded_as_estimate' = 'true'
                    THEN (s.logistics->'deadline_reconciliation'->>'previous_deadline')::timestamptz END
          INTO confirmado, descartado FROM public.pedido_snapshots s WHERE s.pedido_id = NEW.id;
        IF NOT EXISTS (SELECT 1 FROM public.pedidos_shopee so
             WHERE so.codigo_pedido = NEW.marketplace_order_id AND so.ship_by_date IS NOT NULL) THEN
            IF confirmado IS NOT NULL THEN NEW.data_limite_envio := confirmado;
            ELSIF descartado IS NOT NULL AND NEW.data_limite_envio = descartado THEN
                NEW.data_limite_envio := NULL;
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE alvo record;
BEGIN
    FOR alvo IN SELECT p.id,p.data_limite_envio AS anterior
      FROM public.vw_pedidos_pendentes_despacho p
      JOIN public.pedidos_shopee so ON so.codigo_pedido=p.marketplace_order_id AND so.ship_by_date IS NULL
      JOIN public.pedido_snapshots s ON s.pedido_id=p.id
     WHERE p.marketplace_module_id='shopee' AND p.data_limite_envio IS NOT NULL
       AND s.logistics->>'dispatch_deadline_source' IS DISTINCT FROM 'shopee.seller_panel.confirmed'
       AND (s.logistics->>'dispatch_deadline_source' IN ('shopee.days_to_ship','bling.dataPrevista')
            OR (NULLIF(s.logistics->>'deadline','') IS NULL AND so.dias_para_envio > 0
                AND p.data_limite_envio = (((COALESCE(p.data_pagamento_marketplace,p.data_compra_marketplace)
                    AT TIME ZONE 'America/Sao_Paulo')::date + so.dias_para_envio + 1)::timestamp
                    AT TIME ZONE 'America/Sao_Paulo') - interval '1 second'))
    LOOP
        UPDATE public.pedido_snapshots SET logistics =
            (logistics - 'deadline' - 'dispatch_deadline_source' - 'deadline_estimated') || jsonb_build_object(
                'deadline_reconciliation', jsonb_build_object('previous_deadline',alvo.anterior,
                    'discarded_as_estimate',true,'corrected_at',now(),
                    'evidence','Sem ship_by_date; estimativa removida para agrupar pela proxima coleta')),
            updated_at=now() WHERE pedido_id=alvo.id;
        UPDATE public.pedidos SET data_limite_envio=NULL,prazo_postagem_tentativas=0,
            prazo_postagem_proxima_tentativa=NULL,prazo_postagem_motivo=NULL WHERE id=alvo.id;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_bucket_operacional(
    p_prazo timestamptz, p_coleta timestamptz, p_compromisso timestamptz, p_data date
) RETURNS text LANGUAGE sql IMMUTABLE SET search_path TO public, pg_temp AS $$
    SELECT public.despacho_bucket_prazo(COALESCE(p_prazo, p_coleta, p_compromisso), p_data);
$$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_contexto(
    p_integration_id integer, p_modalidade_ids integer[], p_horizonte text[], p_data date
) RETURNS jsonb LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH pendentes AS MATERIALIZED (
    SELECT p.id, p.data_limite_envio, p.compromisso_logistico_em
      FROM public.vw_pedidos_pendentes_despacho p
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND (p.modalidade_logistica_id = ANY(p_modalidade_ids)
            OR (p.modalidade_logistica_id IS NULL AND p_modalidade_ids IS NULL))
), coletas AS MATERIALIZED (
    SELECT * FROM public.despacho_coletas_em_lote(
        (SELECT array_agg(id) FROM pendentes WHERE data_limite_envio IS NULL), now())
), base AS MATERIALIZED (
    SELECT p.id, public.despacho_bucket_operacional(p.data_limite_envio,
        c.coleta_em, p.compromisso_logistico_em, p_data) AS bucket
      FROM pendentes p LEFT JOIN coletas c ON c.pedido_id = p.id
), selecionados AS (SELECT id FROM base WHERE bucket = ANY(p_horizonte)),
ids AS (SELECT COALESCE(array_agg(id ORDER BY id), '{}'::integer[]) AS dados FROM selecionados),
buckets AS (SELECT bucket, count(*) AS qtd FROM base GROUP BY bucket)
SELECT jsonb_build_object(
    'pedido_ids', ids.dados,
    'pedidos', (SELECT COALESCE(jsonb_agg(item || jsonb_build_object('data_coleta_prevista', c.coleta_em)
        ORDER BY ord), '[]'::jsonb)
        FROM jsonb_array_elements(public.despacho_ler_pedidos(ids.dados)) WITH ORDINALITY l(item,ord)
        LEFT JOIN coletas c ON c.pedido_id=(item->>'id')::integer),
    'pacotes', COALESCE((SELECT jsonb_agg(to_jsonb(p)) FROM public.pedidos_pacotes(ids.dados) p), '[]'::jsonb),
    'buckets', COALESCE((SELECT jsonb_object_agg(bucket, qtd) FROM buckets), '{}'::jsonb),
    'total_no', (SELECT count(*) FROM base),
    'contas', COALESCE((SELECT jsonb_object_agg(i.id::text, i.instance_name) FROM public.installed_integrations i
        WHERE i.id IN (SELECT p.erp_integration_id FROM public.pedidos p WHERE p.id = ANY(ids.dados))), '{}'::jsonb)
) FROM ids;
$$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_lote(
    p_integration_id integer, p_modalidade_ids integer[] DEFAULT NULL,
    p_horizonte text[] DEFAULT ARRAY['atrasado','hoje'], p_data date DEFAULT CURRENT_DATE
) RETURNS SETOF integer LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH pendentes AS MATERIALIZED (
    SELECT p.id, p.data_limite_envio, p.compromisso_logistico_em FROM public.vw_pedidos_pendentes_despacho p
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND (p.modalidade_logistica_id = ANY(p_modalidade_ids)
            OR (p.modalidade_logistica_id IS NULL AND p_modalidade_ids IS NULL))
), coletas AS MATERIALIZED (
    SELECT * FROM public.despacho_coletas_em_lote((SELECT array_agg(id) FROM pendentes), now())
)
SELECT p.id FROM pendentes p LEFT JOIN coletas c ON c.pedido_id = p.id
 WHERE public.despacho_bucket_operacional(p.data_limite_envio, c.coleta_em,
        p.compromisso_logistico_em, p_data) = ANY(p_horizonte)
 ORDER BY COALESCE(c.coleta_em, p.compromisso_logistico_em) NULLS LAST, p.id;
$$;


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
        public.despacho_bucket_operacional(p.data_limite_envio, c.coleta_em, p.compromisso_logistico_em, p_data) AS bucket_prazo,
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
