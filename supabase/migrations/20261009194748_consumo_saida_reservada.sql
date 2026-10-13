-- Agrega o consumo diretamente no PostgreSQL para não truncar relatórios no
-- limite de linhas do PostgREST. O histórico continua baseado no ledger.
CREATE OR REPLACE FUNCTION public.consumo_medio_diario(p_dias integer DEFAULT 30)
RETURNS TABLE (
    produto_id integer,
    total_periodo numeric,
    media_diaria numeric,
    periodo_dias integer,
    nome_insumo text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
BEGIN
    IF p_dias IS NULL OR p_dias <= 0 OR p_dias > 3660 THEN
        RAISE EXCEPTION 'p_dias deve estar entre 1 e 3660' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT m.produto_id,
           sum(CASE
               WHEN upper(m.tipo_movimentacao) IN (
                   'COMPENSACAO_CONSUMO', 'COMPENSACAO_CONS_MP',
                   'COMPENSACAO_CONS_INT', 'ESTORNO_CONS_MP', 'ESTORNO_CONS_INT'
               ) THEN -abs(m.quantidade)
               ELSE abs(m.quantidade)
           END)::numeric AS total_periodo,
           (sum(CASE
               WHEN upper(m.tipo_movimentacao) IN (
                   'COMPENSACAO_CONSUMO', 'COMPENSACAO_CONS_MP',
                   'COMPENSACAO_CONS_INT', 'ESTORNO_CONS_MP', 'ESTORNO_CONS_INT'
               ) THEN -abs(m.quantidade)
               ELSE abs(m.quantidade)
           END) / p_dias)::numeric AS media_diaria,
           p_dias,
           coalesce(max(nullif(m.produto_nome, '')), max(p.nome::text)) AS nome_insumo
      FROM public.movimentacoes_estoque m
      LEFT JOIN public.produtos p ON p.id = m.produto_id
     WHERE m.data_movimentacao >= now() - make_interval(days => p_dias)
       AND upper(m.tipo_movimentacao) IN (
           'CONS_MP', 'CONS_INT', 'SAIDA_INSUMO_PRODUCAO', 'SAIDA_RESERVADA',
           'COMPENSACAO_CONSUMO', 'COMPENSACAO_CONS_MP',
           'COMPENSACAO_CONS_INT', 'ESTORNO_CONS_MP', 'ESTORNO_CONS_INT'
       )
     GROUP BY m.produto_id
    HAVING sum(CASE
               WHEN upper(m.tipo_movimentacao) IN (
                   'COMPENSACAO_CONSUMO', 'COMPENSACAO_CONS_MP',
                   'COMPENSACAO_CONS_INT', 'ESTORNO_CONS_MP', 'ESTORNO_CONS_INT'
               ) THEN -abs(m.quantidade)
               ELSE abs(m.quantidade)
           END) <> 0
     ORDER BY m.produto_id;
END;
$function$;

REVOKE ALL ON FUNCTION public.consumo_medio_diario(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.consumo_medio_diario(integer) TO service_role;
