-- `get_bom_for_multiple_products` lia sempre a ficha propria e ignorava
-- `herdar_bom_pai`, enquanto `get_bom_for_produto` aplicava a heranca.
-- `demanda/core.py` usa os dois no mesmo fluxo: para uma variacao que herda, um
-- caminho devolvia lista vazia e o outro a ficha completa. Esta funcao da ao
-- caminho em lote a MESMA regra, sem transformar o batch em N chamadas.
CREATE OR REPLACE FUNCTION public.bom_efetiva_produtos(p_produto_ids integer[])
RETURNS TABLE (
  produto_id integer,
  id integer,
  produto_pai_id integer,
  componente_id integer,
  quantidade_necessaria numeric,
  unidade_medida varchar,
  grupo text,
  is_inherited boolean
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $fn$
  SELECT alvo.id, b.id, b.produto_pai_id, b.componente_id,
         b.quantidade_necessaria, b.unidade_medida, b.grupo, b.is_inherited
    FROM unnest(coalesce(p_produto_ids, '{}'::integer[])) AS alvo(id)
    CROSS JOIN LATERAL public.bom_efetiva_produto(alvo.id) b
   ORDER BY alvo.id, b.id;
$fn$;

COMMENT ON FUNCTION public.bom_efetiva_produtos(integer[]) IS
  'Versao em lote de bom_efetiva_produto. Mesma regra de heranca, uma chamada.';

GRANT EXECUTE ON FUNCTION public.bom_efetiva_produtos(integer[]) TO service_role, authenticated;
