-- E1: a categoria do componente passa a ser a fonte do grupo da BOM.
-- NULL mantém compatibilidade com categorias ainda não classificadas.

ALTER TABLE public.categorias
  ADD COLUMN IF NOT EXISTS grupo_bom text;

ALTER TABLE public.categorias
  DROP CONSTRAINT IF EXISTS categorias_grupo_bom_ck;

ALTER TABLE public.categorias
  ADD CONSTRAINT categorias_grupo_bom_ck
  CHECK (grupo_bom IS NULL OR grupo_bom IN
    ('MIOLO', 'CAPA', 'CONTRA', 'ACABAMENTO', 'EMBALAGEM', 'OUTRO'));

COMMENT ON COLUMN public.categorias.grupo_bom IS
  'Grupo da categoria quando usada como componente de ficha técnica';

CREATE OR REPLACE FUNCTION public.bom_efetiva_produto(p_produto_id integer)
RETURNS TABLE (
  id integer,
  produto_pai_id integer,
  componente_id integer,
  quantidade_necessaria numeric,
  unidade_medida varchar,
  grupo text,
  is_inherited boolean
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $$
  WITH produto AS (
    SELECT p.id, p.parent_id, coalesce(p.herdar_bom_pai, false) AS herdar
      FROM public.produtos p WHERE p.id = p_produto_id
  ), linhas AS (
    SELECT f.*, coalesce(cat.grupo_bom, f.grupo) AS grupo_efetivo,
           false AS herdada
      FROM public.ficha_tecnica f
      LEFT JOIN public.produtos c ON c.id = f.componente_id
      LEFT JOIN public.categorias cat ON cat.id = c.categoria_id
     WHERE f.produto_pai_id = p_produto_id
    UNION ALL
    SELECT f.*, coalesce(cat.grupo_bom, f.grupo) AS grupo_efetivo,
           true AS herdada
      FROM public.ficha_tecnica f
      JOIN produto p ON p.parent_id IS NOT NULL AND p.herdar
                    AND f.produto_pai_id = p.parent_id
      LEFT JOIN public.produtos c ON c.id = f.componente_id
      LEFT JOIN public.categorias cat ON cat.id = c.categoria_id
     WHERE NOT EXISTS (
       SELECT 1
         FROM public.ficha_tecnica própria
         LEFT JOIN public.produtos cp ON cp.id = própria.componente_id
         LEFT JOIN public.categorias ccat ON ccat.id = cp.categoria_id
        WHERE própria.produto_pai_id = p_produto_id
          AND coalesce(ccat.grupo_bom, própria.grupo) IS NOT NULL
          AND coalesce(ccat.grupo_bom, própria.grupo) = coalesce(cat.grupo_bom, f.grupo)
     )
  )
  SELECT l.id, l.produto_pai_id, l.componente_id, l.quantidade_necessaria,
         l.unidade_medida, l.grupo_efetivo, l.herdada
    FROM linhas l
   WHERE l.componente_id IS NOT NULL
   ORDER BY l.id;
$$;