-- Mercado Livre: a torre associa pedidos a coleta usando o SLA de postagem.
-- Shopee continua usando coleta_do_pedido (pagamento + corte), sem alteracao.

CREATE OR REPLACE FUNCTION public.despacho_coleta_do_pedido(
    p_marketplace_module_id text,
    p_modalidade_id integer,
    p_integration_id integer,
    p_referencia timestamptz,
    p_data_limite timestamptz,
    p_agora timestamptz DEFAULT now()
)
RETURNS TABLE (
    corte_em timestamptz,
    coleta_em timestamptz,
    prazo_final_em timestamptz
)
LANGUAGE plpgsql
STABLE
SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    c_tz CONSTANT text := 'America/Sao_Paulo';
    v_tipo text;
    v_deadline_dia date;
    v_limite_dia timestamptz;
    v_corte timestamptz;
    v_coleta timestamptz;
    v_prazo_final timestamptz;
BEGIN
    -- Mantem integralmente o comportamento anterior para Shopee e qualquer
    -- outra origem. Prazo ausente tambem continua usando o fallback atual.
    IF lower(COALESCE(p_marketplace_module_id, '')) <> 'mercadolivre'
       OR p_data_limite IS NULL
       OR p_modalidade_id IS NULL
       OR p_integration_id IS NULL
    THEN
        RETURN QUERY
        SELECT * FROM public.coleta_do_pedido(
            p_modalidade_id, p_integration_id, p_referencia, p_agora
        );
        RETURN;
    END IF;

    SELECT ml.tipo_prazo INTO v_tipo
      FROM public.modalidades_logisticas ml
     WHERE ml.id = p_modalidade_id;

    -- Modalidades relativas nao possuem coleta recorrente. O seu relogio
    -- individual segue sendo apresentado por compromisso_logistico_em.
    IF v_tipo IS DISTINCT FROM 'FIXO' OR p_data_limite <= p_agora THEN
        RETURN QUERY
        SELECT * FROM public.coleta_do_pedido(
            p_modalidade_id, p_integration_id, p_referencia, p_agora
        );
        RETURN;
    END IF;

    v_deadline_dia := (p_data_limite AT TIME ZONE c_tz)::date;
    -- O prazo operacional e um dia de postagem; aceite todas as coletas
    -- daquele dia, mesmo quando a API representa a data como meia-noite.
    v_limite_dia := ((v_deadline_dia + 1)::timestamp AT TIME ZONE c_tz)
                    - interval '1 microsecond';

    -- Procura para tras a janela configurada mais tardia que ainda consegue
    -- receber o pedido (corte futuro) e cuja ultima saida nao passe do SLA.
    -- Quatorze dias cobrem todos os padroes semanais e o offset de coleta D+1.
    -- Bases com agenda dinamica expoem `logistica_lotes`, que ja resolve
    -- excecoes e janelas vindas do marketplace. Bancos anteriores usam as
    -- regras manuais existentes e `janelas_logisticas`.
    IF to_regprocedure('public.logistica_lotes(integer,integer,date,date)') IS NOT NULL THEN
        EXECUTE $query$
            SELECT lote.corte_em, lote.coleta_em, lote.prazo_final_em
              FROM public.logistica_lotes($1, $2, $3, $4) lote
             WHERE lote.corte_em >= GREATEST(COALESCE($5, $6), $6)
               AND lote.prazo_final_em > $6
               AND lote.prazo_final_em <= $7
             ORDER BY lote.prazo_final_em DESC, lote.coleta_em DESC
             LIMIT 1
        $query$
        INTO v_corte, v_coleta, v_prazo_final
        USING p_modalidade_id, p_integration_id, v_deadline_dia - 14,
              v_deadline_dia, p_referencia, p_agora, v_limite_dia;
    ELSE
        SELECT candidato.corte_em, candidato.coleta_em, candidato.prazo_final_em
          INTO v_corte, v_coleta, v_prazo_final
          FROM (
            SELECT (dias.dia + corte.horario_corte) AT TIME ZONE c_tz AS corte_em,
                   min(j.coleta_em) AS coleta_em,
                   max(j.coleta_em) AS prazo_final_em
              FROM generate_series(0, 14) AS recuo(dias)
              CROSS JOIN LATERAL (
                  SELECT (v_deadline_dia - recuo.dias)::date AS dia
              ) AS dias
              CROSS JOIN LATERAL (
                  SELECT min(r.horario_corte) AS horario_corte
                    FROM public.regras_logisticas_integracao r
                   WHERE r.ativo
                     AND r.modalidade_id = p_modalidade_id
                     AND r.marketplace_integration_id = p_integration_id
                     AND r.horario_corte IS NOT NULL
                     AND EXTRACT(isodow FROM dias.dia)::integer = ANY (
                         COALESCE(r.dias_semana, ARRAY[1,2,3,4,5,6,7])
                     )
              ) AS corte
              CROSS JOIN LATERAL public.janelas_logisticas(
                  p_modalidade_id, p_integration_id, dias.dia
              ) AS j
             WHERE corte.horario_corte IS NOT NULL
             GROUP BY dias.dia, corte.horario_corte
            HAVING (dias.dia + corte.horario_corte) AT TIME ZONE c_tz
                       >= GREATEST(COALESCE(p_referencia, p_agora), p_agora)
               AND max(j.coleta_em) > p_agora
               AND max(j.coleta_em) <= v_limite_dia
          ) AS candidato
         ORDER BY candidato.prazo_final_em DESC, candidato.coleta_em DESC
         LIMIT 1;
    END IF;

    IF v_coleta IS NOT NULL THEN
        corte_em := v_corte;
        coleta_em := v_coleta;
        prazo_final_em := v_prazo_final;
        RETURN NEXT;
        RETURN;
    END IF;

    -- Prazo vencido ou sem janela compativel: ainda ha um proximo lote em que
    -- o pedido pode sair. A classificacao atrasado permanece no bucket por SLA.
    RETURN QUERY
    SELECT * FROM public.coleta_do_pedido(
        p_modalidade_id, p_integration_id, p_referencia, p_agora
    );
END;
$function$;

COMMENT ON FUNCTION public.despacho_coleta_do_pedido(text, integer, integer, timestamptz, timestamptz, timestamptz) IS
  'Mercado Livre usa a ultima janela de coleta futura ate data_limite_envio; demais marketplaces e ML sem prazo mantem coleta_do_pedido.';

CREATE OR REPLACE FUNCTION public.despacho_arvore(p_data date DEFAULT CURRENT_DATE)
 RETURNS TABLE(nivel smallint, integration_id integer, marketplace_nome text, modalidade_id integer, modalidade_codigo text, modalidade_nome text, tipo_prazo text, bucket_prazo text, coleta_grupo timestamp with time zone, qtd_pedidos integer, qtd_itens integer, corte_em timestamp with time zone, coleta_em timestamp with time zone, prazo_final_em timestamp with time zone, compromisso_mais_proximo timestamp with time zone, ordem smallint)
 LANGUAGE sql
 STABLE
AS $function$
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
        public.despacho_bucket_prazo(p.data_limite_envio, p_data) AS bucket_prazo,
        COALESCE(c.coleta_em, CASE WHEN p.modalidade_tipo_prazo = 'RELATIVO'
                                   THEN p.compromisso_logistico_em END) AS coleta_grupo,
        p.compromisso_logistico_em,
        c.corte_em,
        c.coleta_em,
        c.prazo_final_em,
        COALESCE(i.qtd, 0) AS qtd_itens
      FROM public.vw_pedidos_pendentes_despacho p
      LEFT JOIN LATERAL public.despacho_coleta_do_pedido(
          p.marketplace_module_id,
          p.modalidade_logistica_id,
          p.marketplace_integration_id,
          COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda),
          p.data_limite_envio,
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
    p_integration_id integer,
    p_modalidade_ids integer[] DEFAULT NULL,
    p_horizonte text[] DEFAULT ARRAY['atrasado', 'hoje'],
    p_data date DEFAULT CURRENT_DATE
)
RETURNS SETOF integer
LANGUAGE sql STABLE
SET search_path TO 'public', 'pg_temp'
AS $function$
    SELECT p.id
      FROM public.vw_pedidos_pendentes_despacho p
      LEFT JOIN LATERAL public.despacho_coleta_do_pedido(
          p.marketplace_module_id,
          p.modalidade_logistica_id,
          p.marketplace_integration_id,
          COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda),
          p.data_limite_envio,
          now()
      ) c ON true
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND (
           p.modalidade_logistica_id = ANY (p_modalidade_ids)
           OR (p.modalidade_logistica_id IS NULL AND p_modalidade_ids IS NULL)
       )
       AND public.despacho_bucket_prazo(p.data_limite_envio, p_data) = ANY (p_horizonte)
     ORDER BY COALESCE(c.coleta_em, p.compromisso_logistico_em) NULLS LAST, p.id;
$function$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_pedidos(
    p_integration_id integer,
    p_modalidade_id integer,
    p_horizonte text[] DEFAULT ARRAY['atrasado', 'hoje'],
    p_data date DEFAULT CURRENT_DATE
)
RETURNS SETOF integer
LANGUAGE sql
STABLE
SET search_path TO 'public', 'pg_temp'
AS $function$
    SELECT p.id
      FROM public.vw_pedidos_pendentes_despacho p
      LEFT JOIN LATERAL public.despacho_coleta_do_pedido(
          p.marketplace_module_id,
          p.modalidade_logistica_id,
          p.marketplace_integration_id,
          COALESCE(p.data_pagamento_marketplace, p.data_compra_marketplace, p.data_venda),
          p.data_limite_envio,
          now()
      ) c ON true
     WHERE p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id IS NOT DISTINCT FROM p_modalidade_id
       AND public.despacho_bucket_prazo(p.data_limite_envio, p_data) = ANY (p_horizonte)
     ORDER BY COALESCE(c.coleta_em, p.compromisso_logistico_em) NULLS LAST, p.id;
$function$;
