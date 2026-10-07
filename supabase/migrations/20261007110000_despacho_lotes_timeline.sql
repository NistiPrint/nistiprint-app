-- Lotes operacionais por conta, agrupamento logístico e dia limite de envio.
-- A agenda recomenda a próxima saída; cortes não alteram o pertencimento.

CREATE OR REPLACE FUNCTION public.despacho_lote_proxima_saida(
    p_modalidade_id integer,
    p_integration_id integer,
    p_data_limite date,
    p_tipo_prazo text,
    p_compromisso timestamptz,
    p_agora timestamptz DEFAULT now()
)
RETURNS timestamptz
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
    SELECT CASE
        WHEN p_tipo_prazo = 'RELATIVO' THEN p_compromisso
        WHEN p_modalidade_id IS NULL OR p_data_limite IS NULL THEN NULL
        ELSE (
            SELECT janela.coleta_em
              FROM generate_series(
                    GREATEST(
                        p_data_limite,
                        (p_agora AT TIME ZONE 'America/Sao_Paulo')::date
                    ),
                    GREATEST(
                        p_data_limite,
                        (p_agora AT TIME ZONE 'America/Sao_Paulo')::date
                    ) + 31,
                    interval '1 day'
              ) AS dias(dia)
              CROSS JOIN LATERAL public.janelas_logisticas(
                    p_modalidade_id, p_integration_id, dia::date
              ) janela
             WHERE janela.coleta_em > p_agora
             ORDER BY janela.coleta_em
             LIMIT 1
        )
    END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_lotes_timeline(p_data date)
RETURNS TABLE (
    integration_id integer,
    marketplace_nome text,
    modalidade_id integer,
    modalidade_codigo text,
    modalidade_nome text,
    tipo_prazo text,
    entrega_rapida boolean,
    data_limite_dia date,
    bucket_prazo text,
    qtd_pedidos integer,
    proxima_saida_em timestamptz,
    saida_apos_prazo boolean
)
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH agrupados AS MATERIALIZED (
    SELECT p.marketplace_integration_id AS integration_id,
           p.marketplace_nome::text,
           p.modalidade_logistica_id AS modalidade_id,
           COALESCE(p.modalidade_codigo, 'NAO_CLASSIFICADA')::text AS modalidade_codigo,
           COALESCE(p.modalidade_nome, 'Modalidade nao classificada')::text AS modalidade_nome,
           COALESCE(p.modalidade_tipo_prazo, 'FIXO')::text AS tipo_prazo,
           COALESCE(m.entrega_rapida, false) AS entrega_rapida,
           (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date AS data_limite_dia,
           CASE
               WHEN p.data_limite_envio IS NULL THEN 'sem_prazo'
               WHEN (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date < p_data THEN 'atrasado'
               WHEN (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date = p_data THEN 'hoje'
               WHEN (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date = p_data + 1 THEN 'amanha'
               ELSE 'depois'
           END AS bucket_prazo,
           count(*)::integer AS qtd_pedidos,
           min(p.compromisso_logistico_em) AS compromisso
      FROM public.vw_pedidos_pendentes_despacho p
      LEFT JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
     GROUP BY p.marketplace_integration_id, p.marketplace_nome,
              p.modalidade_logistica_id, p.modalidade_codigo, p.modalidade_nome,
              p.modalidade_tipo_prazo, m.entrega_rapida,
              (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date,
              CASE
                  WHEN p.data_limite_envio IS NULL THEN 'sem_prazo'
                  WHEN (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date < p_data THEN 'atrasado'
                  WHEN (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date = p_data THEN 'hoje'
                  WHEN (p.data_limite_envio AT TIME ZONE 'America/Sao_Paulo')::date = p_data + 1 THEN 'amanha'
                  ELSE 'depois'
              END
)
SELECT a.integration_id, a.marketplace_nome, a.modalidade_id,
       a.modalidade_codigo, a.modalidade_nome, a.tipo_prazo,
       a.entrega_rapida, a.data_limite_dia, a.bucket_prazo,
       a.qtd_pedidos, saida.proxima_saida_em,
       (a.data_limite_dia IS NOT NULL AND
        (saida.proxima_saida_em AT TIME ZONE 'America/Sao_Paulo')::date > a.data_limite_dia) AS saida_apos_prazo
  FROM agrupados a
  LEFT JOIN LATERAL (
      SELECT public.despacho_lote_proxima_saida(
          a.modalidade_id, a.integration_id, a.data_limite_dia,
          a.tipo_prazo, a.compromisso
      ) AS proxima_saida_em
  ) saida ON true
 ORDER BY proxima_saida_em NULLS LAST, a.data_limite_dia NULLS FIRST,
          a.integration_id, a.modalidade_id;
$$;

-- Mantém a árvore e acrescenta os lotes por prazo em sua leitura já agregada.
CREATE OR REPLACE FUNCTION public.despacho_arvore_contexto(p_data date)
RETURNS jsonb LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH arvore AS MATERIALIZED (SELECT * FROM public.despacho_arvore(p_data)),
integracoes AS (SELECT DISTINCT integration_id FROM arvore WHERE integration_id IS NOT NULL),
janelas AS (
    SELECT a.integration_id, a.modalidade_id,
           jsonb_agg(to_jsonb(j) ORDER BY j.coleta_em) AS dados
      FROM arvore a CROSS JOIN LATERAL public.janelas_logisticas(
          a.modalidade_id, a.integration_id,
          (a.coleta_em AT TIME ZONE 'America/Sao_Paulo')::date
      ) j
     WHERE a.nivel = 1 AND a.modalidade_id IS NOT NULL AND a.coleta_em IS NOT NULL
     GROUP BY a.integration_id, a.modalidade_id
)
SELECT jsonb_build_object(
    'rows', COALESCE((SELECT jsonb_agg(to_jsonb(a)) FROM arvore a), '[]'::jsonb),
    'timeline', COALESCE((SELECT jsonb_agg(to_jsonb(t)) FROM public.despacho_lotes_timeline(p_data) t), '[]'::jsonb),
    'catalogo', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', m.id, 'entrega_rapida', m.entrega_rapida)) FROM public.modalidades_logisticas m), '[]'::jsonb),
    'integracoes', COALESCE((SELECT jsonb_agg(jsonb_build_object('id', i.id, 'module_id', i.module_id)) FROM public.installed_integrations i JOIN integracoes ids ON ids.integration_id = i.id), '[]'::jsonb),
    'composicao', COALESCE((SELECT jsonb_agg(to_jsonb(c)) FROM public.despacho_composicao_situacao(p_data) c), '[]'::jsonb),
    'lotes', COALESCE((SELECT jsonb_agg(to_jsonb(l) || jsonb_build_object('integration_id', ids.integration_id)) FROM integracoes ids CROSS JOIN LATERAL public.despacho_lotes(ids.integration_id) l), '[]'::jsonb),
    'rascunhos', COALESCE((SELECT jsonb_agg(to_jsonb(r)) FROM public.despacho_rascunhos_abertos(p_data) r), '[]'::jsonb),
    'janelas', COALESCE((SELECT jsonb_agg(to_jsonb(j)) FROM janelas j), '[]'::jsonb)
);
$$;

REVOKE ALL ON FUNCTION public.despacho_lote_proxima_saida(integer,integer,date,text,timestamptz,timestamptz),
    public.despacho_lotes_timeline(date)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_lote_proxima_saida(integer,integer,date,text,timestamptz,timestamptz),
    public.despacho_lotes_timeline(date)
    TO service_role;

COMMENT ON FUNCTION public.despacho_lotes_timeline(date) IS
    'Agrupa pendências por conta, modalidade logística e dia limite de envio. Recomenda a primeira saída disponível no dia limite ou na próxima data atendida pela agenda; não usa o corte como critério de pertencimento.';
