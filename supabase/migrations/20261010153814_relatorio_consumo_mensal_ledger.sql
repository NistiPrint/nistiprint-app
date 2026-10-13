-- Relatório mensal de consumo derivado exclusivamente de movimentos físicos
-- confirmados no ledger, com as operações de origem para auditoria.
CREATE OR REPLACE FUNCTION public.relatorio_consumo_mensal_produto(p_produto_id integer)
RETURNS TABLE (
    periodo text,
    consumo_liquido numeric,
    movimentos jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
BEGIN
    IF p_produto_id IS NULL OR p_produto_id <= 0 THEN
        RAISE EXCEPTION 'p_produto_id deve ser um inteiro positivo' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH consumo AS (
        SELECT m.id,
               m.tipo_movimentacao,
               m.quantidade,
               m.operation_id,
               m.data_movimentacao,
               CASE
                   WHEN upper(m.tipo_movimentacao) IN (
                       'COMPENSACAO_CONSUMO', 'COMPENSACAO_CONS_MP',
                       'COMPENSACAO_CONS_INT', 'ESTORNO_CONS_MP', 'ESTORNO_CONS_INT'
                   ) THEN -abs(m.quantidade)
                   ELSE abs(m.quantidade)
               END AS quantidade_liquida
          FROM public.movimentacoes_estoque m
         WHERE m.produto_id = p_produto_id
           AND m.data_movimentacao IS NOT NULL
           AND upper(m.tipo_movimentacao) IN (
               'CONS_MP', 'CONS_INT', 'SAIDA_INSUMO_PRODUCAO', 'SAIDA_RESERVADA',
               'COMPENSACAO_CONSUMO', 'COMPENSACAO_CONS_MP',
               'COMPENSACAO_CONS_INT', 'ESTORNO_CONS_MP', 'ESTORNO_CONS_INT'
           )
    )
    SELECT to_char(date_trunc('month', c.data_movimentacao), 'YYYY-MM') AS periodo,
           sum(c.quantidade_liquida)::numeric AS consumo_liquido,
           jsonb_agg(
               jsonb_build_object(
                   'movimento_id', c.id,
                   'tipo', c.tipo_movimentacao,
                   'quantidade_liquida', c.quantidade_liquida,
                   'operation_id', c.operation_id
               ) ORDER BY c.data_movimentacao, c.id
           ) AS movimentos
      FROM consumo c
     GROUP BY date_trunc('month', c.data_movimentacao)
     ORDER BY date_trunc('month', c.data_movimentacao);
END;
$function$;

REVOKE ALL ON FUNCTION public.relatorio_consumo_mensal_produto(integer)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.relatorio_consumo_mensal_produto(integer)
    TO service_role;
