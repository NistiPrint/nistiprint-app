-- Lotes pendentes da Torre com os pedidos de cada um, para a previsão de
-- produção. É despacho_lotes_timeline (20261007110000) acrescida de
-- array_agg(p.id) e de um recorte por horizonte: o GROUP BY e o CASE de bucket
-- são os mesmos de propósito, para que um lote aqui seja exatamente o card da
-- Torre. Não consolida itens; isso fica com despacho_consolidar_pedidos.

CREATE OR REPLACE FUNCTION public.despacho_previsao_lotes(p_data date, p_horizonte text[])
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
    pedido_ids integer[],
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
           array_agg(p.id ORDER BY p.id)::integer[] AS pedido_ids,
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
       a.qtd_pedidos, a.pedido_ids, saida.proxima_saida_em,
       (a.data_limite_dia IS NOT NULL AND
        (saida.proxima_saida_em AT TIME ZONE 'America/Sao_Paulo')::date > a.data_limite_dia) AS saida_apos_prazo
  FROM agrupados a
  LEFT JOIN LATERAL (
      SELECT public.despacho_lote_proxima_saida(
          a.modalidade_id, a.integration_id, a.data_limite_dia,
          a.tipo_prazo, a.compromisso
      ) AS proxima_saida_em
  ) saida ON true
 WHERE a.bucket_prazo = ANY(p_horizonte)
 ORDER BY saida.proxima_saida_em NULLS LAST, a.data_limite_dia NULLS FIRST,
          a.integration_id, a.modalidade_id;
$$;

-- Mesma escolha explícita de status das demais leituras da Torre: a opção é
-- local à transação, então consultas paralelas nunca compartilham o filtro.
CREATE OR REPLACE FUNCTION public.despacho_previsao_lotes(
    p_data date, p_horizonte text[], p_incluir_pronto boolean
)
RETURNS TABLE (
    integration_id integer, marketplace_nome text, modalidade_id integer,
    modalidade_codigo text, modalidade_nome text, tipo_prazo text,
    entrega_rapida boolean, data_limite_dia date, bucket_prazo text,
    qtd_pedidos integer, pedido_ids integer[], proxima_saida_em timestamptz,
    saida_apos_prazo boolean
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO public, pg_temp AS $$
BEGIN
    PERFORM set_config('app.despacho_incluir_pronto', COALESCE(p_incluir_pronto, false)::text, true);
    RETURN QUERY SELECT * FROM public.despacho_previsao_lotes(p_data, p_horizonte);
END;
$$;

REVOKE ALL ON FUNCTION public.despacho_previsao_lotes(date, text[]),
    public.despacho_previsao_lotes(date, text[], boolean)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_previsao_lotes(date, text[]),
    public.despacho_previsao_lotes(date, text[], boolean)
    TO service_role;

COMMENT ON FUNCTION public.despacho_previsao_lotes(date, text[]) IS
    'Lotes pendentes da Torre (mesmo agrupamento de despacho_lotes_timeline) com os ids dos pedidos, recortados por bucket de prazo. Base da previsão de miolos antes da publicação.';

NOTIFY pgrst, 'reload schema';
