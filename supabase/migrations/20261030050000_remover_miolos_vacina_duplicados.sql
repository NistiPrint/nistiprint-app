-- Consolidação pontual revisada: os SKUs legados não definem uma nova regra
-- geral de extração. Permanecem no relatório de SKUs inválidos.
-- Cópias integrais dos produtos e BOMs ficam no log antes da exclusão.
BEGIN;

LOCK TABLE public.produtos, public.ficha_tecnica IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMP TABLE _vacina_mapa ON COMMIT DROP AS
SELECT p.id AS source_id, c.id AS canonical_id, reviewed.codigo
FROM (VALUES
  ('MIOLO-VACINA_MENINO-112P-PADRAO', 'VACMNO'),
  ('MIOLO-VACINA_MENINA-112P-PADRAO-REF111', 'VACMNA'),
  ('MIOLO-VACINA-112P-PADRAO-REF111', 'VACMNO'),
  ('MIOLO-VACINA_MENINO-120P-PADRAO', 'VACMNO'),
  ('MIOLO-VACINA_MENINO-112P-PADRAO-REF111', 'VACMNO')
) AS reviewed(sku, codigo)
JOIN public.produtos p ON p.sku = reviewed.sku AND p.categoria_id = 6
JOIN public.produtos c ON c.sku = 'MIOLO-' || reviewed.codigo
  AND c.categoria_id = 6 AND c.tipo_material = 'intermediario';

DO $$
DECLARE
  fk record;
  blocked boolean;
  run uuid := gen_random_uuid();
BEGIN
  -- Bloqueia destinos ausentes e referências novas não contempladas na revisão.
  IF (SELECT count(*) FROM _vacina_mapa) <>
     (SELECT count(*) FROM public.produtos WHERE sku IN (
       'MIOLO-VACINA_MENINO-112P-PADRAO',
       'MIOLO-VACINA_MENINA-112P-PADRAO-REF111',
       'MIOLO-VACINA-112P-PADRAO-REF111',
       'MIOLO-VACINA_MENINO-120P-PADRAO',
       'MIOLO-VACINA_MENINO-112P-PADRAO-REF111'
     )) THEN
    RAISE EXCEPTION 'Miolo canônico ausente ou origem fora da categoria Miolo';
  END IF;

  FOR fk IN
    SELECT c.conrelid::regclass AS relation, a.attname AS col
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    WHERE c.contype = 'f' AND c.confrelid = 'public.produtos'::regclass
      AND cardinality(c.conkey) = 1
      AND NOT (c.conrelid = 'public.ficha_tecnica'::regclass
        AND a.attname IN ('produto_pai_id', 'componente_id'))
  LOOP
    EXECUTE format(
      'SELECT EXISTS(SELECT 1 FROM %s t JOIN _vacina_mapa m ON t.%I=m.source_id)',
      fk.relation, fk.col
    ) INTO blocked;
    IF blocked THEN
      RAISE EXCEPTION 'Referência não revisada em %.%', fk.relation, fk.col;
    END IF;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM public.ficha_tecnica ft
    JOIN _vacina_mapa m ON m.source_id = ft.componente_id
    JOIN public.produtos p ON p.id = ft.produto_pai_id
    WHERE p.formato = 'kit' OR p.categoria_id NOT IN (7, 11)
  ) THEN
    RAISE EXCEPTION 'Origem usada por kit ou categoria fora do escopo';
  END IF;

  IF EXISTS (
    SELECT 1 FROM public.ficha_tecnica ft
    JOIN _vacina_mapa m ON m.source_id = ft.componente_id
    JOIN public.ficha_tecnica other ON other.produto_pai_id = ft.produto_pai_id
      AND other.componente_id = m.canonical_id
  ) THEN
    RAISE EXCEPTION 'BOM com destino já existente exige revisão de quantidade';
  END IF;

  -- Registra o produto, as receitas antigas, os vínculos que serão transferidos
  -- e a receita canônica preservada (112/120 páginas têm consumos diferentes).
  INSERT INTO public.miolo_codigo_limpeza_log
    (run_id, action, codigo, miolo_origem_id, miolo_canonico_id, details)
  SELECT run, 'backup_exclusao_vacina', m.codigo, m.source_id, m.canonical_id,
    jsonb_build_object(
      'produto', to_jsonb(p),
      'bom_origem', COALESCE((SELECT jsonb_agg(to_jsonb(ft))
        FROM public.ficha_tecnica ft WHERE ft.produto_pai_id = p.id), '[]'::jsonb),
      'vinculos_anteriores', COALESCE((SELECT jsonb_agg(to_jsonb(ft))
        FROM public.ficha_tecnica ft WHERE ft.componente_id = p.id), '[]'::jsonb),
      'bom_canonica_preservada', COALESCE((SELECT jsonb_agg(to_jsonb(ft))
        FROM public.ficha_tecnica ft WHERE ft.produto_pai_id = m.canonical_id), '[]'::jsonb),
      'resolucao', 'consolidacao_pontual_revisada_vacina',
      'conflito_consumo', 'Receita canônica preservada; receita descritiva arquivada'
    )
  FROM _vacina_mapa m JOIN public.produtos p ON p.id = m.source_id;

  UPDATE public.ficha_tecnica ft
  SET componente_id = m.canonical_id,
      sku_componente = 'MIOLO-' || m.codigo,
      updated_at = now()
  FROM _vacina_mapa m WHERE ft.componente_id = m.source_id;

  -- Somente receitas pertencentes aos cadastros duplicados são removidas.
  DELETE FROM public.ficha_tecnica ft USING _vacina_mapa m
  WHERE ft.produto_pai_id = m.source_id;

  -- Repete a verificação integral após transferir os vínculos e retirar receitas.
  FOR fk IN
    SELECT c.conrelid::regclass AS relation, a.attname AS col
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    WHERE c.contype = 'f' AND c.confrelid = 'public.produtos'::regclass
      AND cardinality(c.conkey) = 1
  LOOP
    EXECUTE format(
      'SELECT EXISTS(SELECT 1 FROM %s t JOIN _vacina_mapa m ON t.%I=m.source_id)',
      fk.relation, fk.col
    ) INTO blocked;
    IF blocked THEN
      RAISE EXCEPTION 'Referência remanescente em %.%', fk.relation, fk.col;
    END IF;
  END LOOP;

  DELETE FROM public.produtos p USING _vacina_mapa m WHERE p.id = m.source_id;

  INSERT INTO public.miolo_codigo_limpeza_log
    (run_id, action, codigo, miolo_origem_id, miolo_canonico_id, details)
  SELECT run, 'miolo_vacina_removido', codigo, source_id, canonical_id,
    jsonb_build_object('backup_action', 'backup_exclusao_vacina')
  FROM _vacina_mapa;
END $$;

COMMIT;
