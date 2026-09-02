-- F2/F3: catálogo inicial de eixos e backfill somente de relações inequívocas.
-- O SKU é lido apenas nesta migração pontual; a resolução futura usa referências.

CREATE TABLE IF NOT EXISTS public.produto_variacao_backfill_revisao (
  produto_id integer PRIMARY KEY REFERENCES public.produtos(id) ON DELETE CASCADE,
  sku_observado text NOT NULL,
  motivo text NOT NULL,
  criado_em timestamptz NOT NULL DEFAULT now(),
  resolvido_em timestamptz
);

INSERT INTO public.produto_eixos (codigo, nome, escopo, ordem_sku) VALUES
  ('miolo', 'Miolo', 'produto', 1),
  ('estampa', 'Estampa', 'variacao', 2),
  ('acabamento', 'Acabamento', 'variacao', 3)
ON CONFLICT (codigo) DO NOTHING;

-- Miolos existentes são opções reais, não nomes deduzidos de produtos acabados.
INSERT INTO public.produto_eixo_opcoes (eixo_id, codigo, nome)
SELECT e.id,
       upper(regexp_replace(p.sku, '^MIOLO-', '', 'i')),
       p.nome
  FROM public.produto_eixos e
  JOIN public.produtos p ON p.categoria_id = 6
 WHERE e.codigo = 'miolo'
   AND p.sku IS NOT NULL
ON CONFLICT (eixo_id, codigo) DO NOTHING;

-- Cada estampa é representada pelos componentes de capa cadastrados.
-- O código é normalizado a partir do nome/SKU do componente e não altera o SKU.
INSERT INTO public.produto_eixo_opcoes (eixo_id, codigo, nome)
SELECT DISTINCT ON (e.id, upper(regexp_replace(
         regexp_replace(regexp_replace(p.sku, '^\\s*', '', ''),
                        '-(CAPA|CONTRA)(PRONTA|IMPRESSA)?\\s*$', '', 'i'),
         '\\s+', ' ', 'g')))
       e.id,
       upper(regexp_replace(
         regexp_replace(regexp_replace(p.sku, '^\\s*', '', ''),
                        '-(CAPA|CONTRA)(PRONTA|IMPRESSA)?\\s*$', '', 'i'),
         '\\s+', ' ', 'g')),
       btrim(regexp_replace(p.nome, '\\s*-\\s*(Capa|Contra).*$', '', 'i'))
  FROM public.produto_eixos e
  JOIN public.produtos p ON p.categoria_id IN (3, 10)
 WHERE e.codigo = 'estampa'
   AND p.sku IS NOT NULL
   AND p.sku ~* '(CAPA|CONTRA)'
ON CONFLICT (eixo_id, codigo) DO NOTHING;

INSERT INTO public.produto_eixo_opcoes (eixo_id, codigo, nome)
SELECT e.id, x.codigo, x.nome
  FROM public.produto_eixos e
  CROSS JOIN (VALUES
    ('PXP','PXP'), ('BXB','BXB'), ('BXR','BXR'), ('BXA','BXA'),
    ('PXV','PXV'), ('PXR','PXR'), ('BAA','BAA'), ('PAA','PAA'), ('RBB','RBB')
  ) AS x(codigo, nome)
 WHERE e.codigo = 'acabamento'
ON CONFLICT (eixo_id, codigo) DO NOTHING;

-- Um produto acabado com exatamente um componente da categoria Miolo tem
-- relação suficiente para o backfill, sem interpretar estampa/acabamento.
INSERT INTO public.produto_variacao_valores (produto_id, eixo_id, opcao_id)
SELECT p.id, e.id, o.id
  FROM public.produtos p
  JOIN public.ficha_tecnica f ON f.produto_pai_id = p.id
  JOIN public.produtos mi ON mi.id = f.componente_id AND mi.categoria_id = 6
  JOIN public.produto_eixos e ON e.codigo = 'miolo'
  JOIN public.produto_eixo_opcoes o ON o.eixo_id = e.id
   AND o.codigo = upper(regexp_replace(mi.sku, '^MIOLO-', '', 'i'))
 WHERE p.tipo_produto = 'PRODUTO_ACABADO'
 GROUP BY p.id, e.id, o.id
 HAVING count(*) = 1
ON CONFLICT (produto_id, eixo_id) DO NOTHING;

INSERT INTO public.produto_variacao_backfill_revisao (produto_id, sku_observado, motivo)
SELECT p.id, p.sku,
       CASE WHEN count(DISTINCT f.componente_id) FILTER (WHERE c.categoria_id = 6) <> 1
            THEN 'miolo ausente ou múltiplo'
            ELSE 'estampa/acabamento exigem revisão do cadastro' END
  FROM public.produtos p
  LEFT JOIN public.ficha_tecnica f ON f.produto_pai_id = p.id
  LEFT JOIN public.produtos c ON c.id = f.componente_id
 WHERE p.tipo_produto = 'PRODUTO_ACABADO'
 GROUP BY p.id, p.sku
 HAVING count(DISTINCT f.componente_id) FILTER (WHERE c.categoria_id = 6) <> 1
     OR NOT EXISTS (
       SELECT 1 FROM public.produto_variacao_valores v
       JOIN public.produto_eixos e ON e.id = v.eixo_id
       WHERE v.produto_id = p.id AND e.codigo = 'estampa'
     )
ON CONFLICT (produto_id) DO NOTHING;

CREATE OR REPLACE FUNCTION public.resolver_produto_completo(p_codigo text, p_plataforma text DEFAULT NULL)
RETURNS TABLE(produto_id integer, produto_sku text, produto_nome text, variacao text,
              miolo_id integer, miolo_sku text, miolo_nome text, origem text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_cat_miolo integer;
  v_produto integer;
  v_fb record;
BEGIN
  SELECT (valor #>> '{}')::integer INTO v_cat_miolo
    FROM public.configuracoes_aplicacao
   WHERE nome = 'producao_miolos_category_id';
  v_cat_miolo := COALESCE(v_cat_miolo, 6);
  v_produto := public.resolver_produto_por_codigo(p_codigo, p_plataforma);

  IF v_produto IS NOT NULL THEN
    RETURN QUERY
    SELECT p.id, p.sku::text, p.nome::text,
           (SELECT o.nome::text
              FROM public.produto_variacao_valores vv
              JOIN public.produto_eixos e ON e.id=vv.eixo_id AND e.codigo='estampa'
              JOIN public.produto_eixo_opcoes o ON o.id=vv.opcao_id
             WHERE vv.produto_id=p.id LIMIT 1),
           m.id, m.sku::text, m.nome::text,
           CASE WHEN EXISTS (SELECT 1 FROM public.produto_variacao_valores vv
                              JOIN public.produto_eixos e ON e.id=vv.eixo_id AND e.codigo='miolo'
                             WHERE vv.produto_id=p.id)
                THEN 'eixo_cadastrado' ELSE
                (CASE WHEN upper(btrim(p.sku::text))=upper(btrim(p_codigo))
                      THEN 'sku_interno' ELSE 'apelido' END) END::text
      FROM public.produtos p
      LEFT JOIN LATERAL (
        SELECT mi.id, mi.sku, mi.nome
          FROM public.produto_variacao_valores vv
          JOIN public.produto_eixos e ON e.id=vv.eixo_id AND e.codigo='miolo'
          JOIN public.produto_eixo_opcoes o ON o.id=vv.opcao_id
          JOIN public.produtos mi ON upper(regexp_replace(mi.sku,'^MIOLO-','', 'i'))=o.codigo
         WHERE vv.produto_id=p.id
         LIMIT 1
      ) m ON true
     WHERE p.id=v_produto;
    RETURN;
  END IF;

  SELECT * INTO v_fb FROM public.resolver_miolo_por_prefixo(p_codigo,p_plataforma,true);
  IF v_fb.miolo_id IS NULL THEN RETURN; END IF;
  RETURN QUERY SELECT NULL::integer,NULL::text,NULL::text,NULL::text,
                      mi.id,mi.sku::text,mi.nome::text,
                      ('miolo_por_'||v_fb.origem)::text
                 FROM public.produtos mi WHERE mi.id=v_fb.miolo_id;
END $$;