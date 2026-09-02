-- F5: fonte única para a BOM efetiva e validações de kit.
-- NULL em ficha_tecnica.grupo preserva a semântica legada.

INSERT INTO public.categoria_bom_regras
  (categoria_pai_id, nome_grupo, categoria_componente_id, min_quantidade, max_quantidade, ordem)
SELECT x.categoria_pai_id, x.nome_grupo, x.categoria_componente_id,
       x.min_quantidade, x.max_quantidade, x.ordem
  FROM (VALUES
    (7, 'Miolo', 6, 1::numeric, 1::numeric, 1),
    (7, 'Capa', 3, 1::numeric, 1::numeric, 2),
    (7, 'Contra', 10, 1::numeric, 1::numeric, 3),
    (7, 'Acabamento', 4, 1::numeric, NULL::numeric, 4),
    (7, 'Embalagem', 5, 1::numeric, NULL::numeric, 5)
  ) AS x(categoria_pai_id,nome_grupo,categoria_componente_id,min_quantidade,max_quantidade,ordem)
WHERE NOT EXISTS (
  SELECT 1 FROM public.categoria_bom_regras r
   WHERE r.categoria_pai_id=x.categoria_pai_id AND r.nome_grupo=x.nome_grupo
);

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
  ), proprio AS (
    SELECT f.* FROM public.ficha_tecnica f WHERE f.produto_pai_id = p_produto_id
  ), grupos_proprios AS (
    SELECT DISTINCT grupo FROM proprio WHERE grupo IS NOT NULL
  ), pai AS (
    SELECT f.* FROM public.ficha_tecnica f
    JOIN produto p ON p.parent_id IS NOT NULL AND p.herdar
     AND f.produto_pai_id = p.parent_id
    WHERE f.grupo IS NULL OR NOT EXISTS (
      SELECT 1 FROM grupos_proprios g WHERE g.grupo = f.grupo
    )
  )
  SELECT f.id, f.produto_pai_id, f.componente_id, f.quantidade_necessaria,
         f.unidade_medida, f.grupo,
         (f.produto_pai_id <> p_produto_id) AS is_inherited
    FROM (SELECT * FROM proprio UNION ALL SELECT * FROM pai) f
  WHERE f.componente_id IS NOT NULL
  ORDER BY f.id;
$$;

CREATE OR REPLACE FUNCTION public.validar_componente_kit()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  pai_formato text;
  componente_tipo text;
  componente_formato text;
BEGIN
  SELECT formato INTO pai_formato FROM public.produtos WHERE id = NEW.produto_pai_id;
  IF pai_formato = 'kit' THEN
    SELECT tipo_produto, formato INTO componente_tipo, componente_formato
      FROM public.produtos WHERE id = NEW.componente_id;
    IF componente_tipo IS DISTINCT FROM 'PRODUTO_ACABADO' THEN
      RAISE EXCEPTION 'Componente de kit deve ser PRODUTO_ACABADO (produto %)', NEW.componente_id;
    END IF;
    IF componente_formato = 'kit' THEN
      RAISE EXCEPTION 'Kit não pode conter outro kit (profundidade máxima 1)';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_validar_componente_kit ON public.ficha_tecnica;
CREATE TRIGGER trg_validar_componente_kit
  BEFORE INSERT OR UPDATE OF produto_pai_id, componente_id ON public.ficha_tecnica
  FOR EACH ROW EXECUTE FUNCTION public.validar_componente_kit();