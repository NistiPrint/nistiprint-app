-- A3: `tem_capa` e `tem_acabamento` eram falsos nos 357 produtos.
--
-- Havia DUAS implementacoes da mesma pergunta, e as duas erravam:
--   v_produto_prontidao (20260831150000) casava por NOME DE CATEGORIA com LIKE,
--     e as duas categorias de capa se chamam "Capa/Contra (...)": o filtro
--     `LIKE '%capa%' AND NOT LIKE '%contra%'` elimina as duas. `tem_acabamento`
--     procurava '%acabamento%'/'%encader%', e nenhuma categoria tem esse nome.
--   produto_prontidao (20260831270000) usava coalesce(cat.grupo_bom, f.grupo),
--     que depende de classificacao - e 0 de 7 categorias estao classificadas.
--
-- Aqui o grupo passa a ter UMA fonte, com precedencia explicita, e a derivacao
-- funciona sem ninguem classificar nada. O ponto que quebrava a classificacao
-- por categoria continua valendo: as categorias 3 e 10 tem metade capa e metade
-- contra dentro (46/45 e 45/44), entao capa x contra sai do NOME do componente
-- - que e o mesmo sinal que `resolver_produto_completo` ja usa ('capa pronta').
--
-- Medido depois de aplicar: tem_capa 0 -> 86, tem_contra 0 -> 82,
-- tem_acabamento 0 -> 295, ficha_completa 315 de 357. A consolidacao de pedidos
-- nao muda: 649 linhas / 16.715 pecas, iguais.

CREATE OR REPLACE FUNCTION public.grupo_bom_do_componente(
    p_componente_id integer,
    p_grupo_linha   text DEFAULT NULL
)
RETURNS text
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $fn$
  WITH cfg AS (
    SELECT coalesce((SELECT (valor #>> '{}') FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_miolos_category_id'), '6')::integer AS cat_miolo
  ), comp AS (
    SELECT c.id, c.nome, c.categoria_id, cat.grupo_bom
      FROM public.produtos c
      LEFT JOIN public.categorias cat ON cat.id = c.categoria_id
     WHERE c.id = p_componente_id
  )
  SELECT coalesce(
    nullif(btrim(p_grupo_linha), ''),
    comp.grupo_bom,
    CASE WHEN comp.categoria_id = cfg.cat_miolo THEN 'MIOLO' END,
    CASE WHEN comp.nome ~* 'contra' THEN 'CONTRA'
         WHEN comp.nome ~* 'capa'   THEN 'CAPA' END,
    (SELECT upper(r.nome_grupo) FROM public.categoria_bom_regras r
      WHERE r.categoria_componente_id = comp.categoria_id
        AND upper(r.nome_grupo) NOT IN ('CAPA', 'CONTRA')
      ORDER BY r.ordem, r.id LIMIT 1)
  )
    FROM comp CROSS JOIN cfg;
$fn$;

COMMENT ON FUNCTION public.grupo_bom_do_componente(integer, text) IS
  'Grupo efetivo de uma linha de ficha tecnica. Precedencia: grupo da linha > grupo da categoria > miolo por categoria configurada > capa/contra pelo nome do componente > regra da categoria. Fonte unica: bom_efetiva_produto e produto_prontidao usam esta funcao.';

CREATE OR REPLACE FUNCTION public.bom_efetiva_produto(p_produto_id integer)
RETURNS TABLE (
  id integer, produto_pai_id integer, componente_id integer,
  quantidade_necessaria numeric, unidade_medida varchar, grupo text,
  is_inherited boolean
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $fn$
  WITH produto AS (
    SELECT p.id, p.sku, p.parent_id,
           (p.parent_id IS NOT NULL AND coalesce(p.herdar_bom_pai, false)) AS herda
      FROM public.produtos p WHERE p.id = p_produto_id
  ),
  proprio AS (
    SELECT f.*, public.grupo_bom_do_componente(f.componente_id, f.grupo) AS grupo_efetivo
      FROM public.ficha_tecnica f
      CROSS JOIN produto pr
     WHERE f.produto_pai_id = pr.id
        OR (f.produto_pai_id IS NULL AND f.sku_produto_pai IS NOT NULL
            AND f.sku_produto_pai = pr.sku)
  ),
  grupos_proprios AS (
    SELECT DISTINCT grupo_efetivo FROM proprio WHERE grupo_efetivo IS NOT NULL
  ),
  modo AS (
    SELECT pr.herda AS herda,
           (pr.herda AND EXISTS (SELECT 1 FROM grupos_proprios)) AS merge_por_grupo
      FROM produto pr
  ),
  pai AS (
    SELECT f.*, public.grupo_bom_do_componente(f.componente_id, f.grupo) AS grupo_efetivo
      FROM public.ficha_tecnica f
      CROSS JOIN produto pr
      CROSS JOIN modo m
     WHERE m.herda AND f.produto_pai_id = pr.parent_id
       AND (NOT m.merge_por_grupo
            OR NOT EXISTS (
                 SELECT 1 FROM grupos_proprios g
                  WHERE g.grupo_efetivo = public.grupo_bom_do_componente(f.componente_id, f.grupo)
               ))
  ),
  linhas AS (
    SELECT p.*, false AS herdada FROM proprio p
     CROSS JOIN modo m WHERE NOT m.herda OR m.merge_por_grupo
    UNION ALL
    SELECT p.*, true AS herdada FROM pai p
  )
  SELECT l.id, l.produto_pai_id, l.componente_id, l.quantidade_necessaria,
         l.unidade_medida, l.grupo_efetivo, l.herdada
    FROM linhas l WHERE l.componente_id IS NOT NULL ORDER BY l.id;
$fn$;

CREATE OR REPLACE FUNCTION public.produto_prontidao(p_produto_id integer)
RETURNS TABLE (produto_id integer, estagio public.estagio_produto, sku text, nome text,
               categoria_id integer, tem_ficha boolean, tem_miolo boolean, tem_capa boolean,
               tem_contra boolean, tem_acabamento boolean, ficha_completa boolean,
               exige_arte boolean, arte_confirmada boolean, eixos_completos boolean,
               tem_apelido_externo boolean, tem_custo boolean, tem_anuncio boolean,
               proximo_estagio public.estagio_produto, pendencias text[], tags text[])
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $fn$
WITH p AS (
  SELECT pr.*, c.permite_arte FROM public.produtos pr
   LEFT JOIN public.categorias c ON c.id = pr.categoria_id WHERE pr.id = p_produto_id
),
-- Le a ficha EFETIVA, nao a tabela crua: uma variacao que herda tem que ser
-- julgada pela ficha que ela realmente usa, senao toda variacao nasce "sem ficha".
bom AS (
  SELECT public.grupo_bom_do_componente(b.componente_id, b.grupo) AS grupo
    FROM public.bom_efetiva_produto(p_produto_id) b
),
gates AS (
  SELECT p.*,
    EXISTS (SELECT 1 FROM bom) AS tem_ficha,
    EXISTS (SELECT 1 FROM bom WHERE grupo = 'MIOLO') AS tem_miolo,
    EXISTS (SELECT 1 FROM bom WHERE grupo = 'CAPA') AS tem_capa,
    EXISTS (SELECT 1 FROM bom WHERE grupo = 'CONTRA') AS tem_contra,
    EXISTS (SELECT 1 FROM bom WHERE grupo = 'ACABAMENTO') AS tem_acabamento,
    (NOT EXISTS (SELECT 1 FROM public.categoria_bom_regras r WHERE r.categoria_pai_id = p.categoria_id)
     OR NOT EXISTS (SELECT 1 FROM public.categoria_bom_regras r
                     WHERE r.categoria_pai_id = p.categoria_id
                       AND NOT EXISTS (SELECT 1 FROM bom WHERE bom.grupo = upper(r.nome_grupo)))
    ) AS ficha_completa,
    (coalesce(p.permite_arte, false)
     OR EXISTS (SELECT 1 FROM public.bom_efetiva_produto(p.id) b
                 JOIN public.produtos c ON c.id = b.componente_id
                 JOIN public.categorias cc ON cc.id = c.categoria_id
                WHERE cc.permite_arte)) AS exige_arte,
    (p.arte_confirmada_em IS NOT NULL) AS arte_confirmada,
    (p.parent_id IS NULL OR NOT EXISTS (
       SELECT 1 FROM public.produto_pai_eixos pe
        WHERE pe.produto_pai_id = p.parent_id
          AND NOT EXISTS (SELECT 1 FROM public.produto_variacao_valores vv
                           WHERE vv.produto_id = p.id AND vv.eixo_id = pe.eixo_id))) AS eixos_completos,
    EXISTS (SELECT 1 FROM public.produtos_externos e WHERE e.produto_id = p.id) AS tem_apelido_externo,
    (coalesce(p.preco_custo, 0) > 0) AS tem_custo,
    EXISTS (SELECT 1 FROM public.produto_anuncios a WHERE a.produto_id = p.id AND a.status = 'ativo') AS tem_anuncio
  FROM p
),
resultado AS (
  SELECT g.*, array_remove(ARRAY[
    CASE WHEN NOT g.tem_ficha THEN 'sem ficha' END,
    CASE WHEN NOT g.ficha_completa THEN 'ficha incompleta' END,
    CASE WHEN g.exige_arte AND NOT g.arte_confirmada THEN 'arte não confirmada pelo agente' END,
    CASE WHEN NOT g.eixos_completos THEN 'eixos incompletos' END,
    CASE WHEN NOT g.tem_apelido_externo THEN 'sem apelido externo' END,
    CASE WHEN NOT g.tem_custo THEN 'sem custo' END], NULL) AS pendencias
  FROM gates g
)
SELECT r.id, r.estagio, r.sku::text, r.nome::text, r.categoria_id, r.tem_ficha, r.tem_miolo,
       r.tem_capa, r.tem_contra, r.tem_acabamento, r.ficha_completa, r.exige_arte,
       r.arte_confirmada, r.eixos_completos, r.tem_apelido_externo, r.tem_custo, r.tem_anuncio,
       CASE WHEN cardinality(r.pendencias) = 0 THEN 'PUBLICADO'::public.estagio_produto
            WHEN r.exige_arte AND NOT r.arte_confirmada THEN 'ARTE_PENDENTE'::public.estagio_produto
            WHEN NOT r.ficha_completa OR NOT r.eixos_completos THEN 'FICHA_OK'::public.estagio_produto
            WHEN NOT r.tem_apelido_externo OR NOT r.tem_anuncio THEN 'CANAL_OK'::public.estagio_produto
            ELSE 'RASCUNHO'::public.estagio_produto END,
       r.pendencias,
       coalesce((SELECT array_agg(t.nome ORDER BY t.nome) FROM public.produto_tags pt
                  JOIN public.tags t ON t.id = pt.tag_id WHERE pt.produto_id = r.id), '{}'::text[])
  FROM resultado r;
$fn$;

-- Duas respostas para a mesma pergunta e como a divergencia entra: a view era a
-- segunda, com a regra por nome de categoria que nunca funcionou.
DROP VIEW IF EXISTS public.v_produto_prontidao;

REVOKE ALL ON FUNCTION public.produto_prontidao(integer) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.grupo_bom_do_componente(integer, text) TO service_role, authenticated;
