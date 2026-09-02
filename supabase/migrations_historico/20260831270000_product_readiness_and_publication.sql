-- E6: prontidão calculada no banco e publicação explícita.
CREATE OR REPLACE FUNCTION public.produto_prontidao(p_produto_id integer)
RETURNS TABLE (
  produto_id integer, estagio public.estagio_produto, sku text, nome text,
  categoria_id integer, tem_ficha boolean, tem_miolo boolean, tem_capa boolean,
  tem_contra boolean, tem_acabamento boolean, ficha_completa boolean,
  exige_arte boolean, arte_confirmada boolean, eixos_completos boolean,
  tem_apelido_externo boolean, tem_custo boolean, tem_anuncio boolean,
  proximo_estagio public.estagio_produto, pendencias text[], tags text[]
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $$
WITH p AS (
  SELECT pr.*, c.permite_arte
    FROM public.produtos pr
    LEFT JOIN public.categorias c ON c.id=pr.categoria_id
   WHERE pr.id=p_produto_id
), bom AS (
  SELECT f.produto_pai_id,
         bool_or(coalesce(cat.grupo_bom,f.grupo)='MIOLO') AS miolo,
         bool_or(coalesce(cat.grupo_bom,f.grupo)='CAPA') AS capa,
         bool_or(coalesce(cat.grupo_bom,f.grupo)='CONTRA') AS contra,
         bool_or(coalesce(cat.grupo_bom,f.grupo)='ACABAMENTO') AS acabamento
    FROM public.ficha_tecnica f
    LEFT JOIN public.produtos c ON c.id=f.componente_id
    LEFT JOIN public.categorias cat ON cat.id=c.categoria_id
   WHERE f.produto_pai_id=p_produto_id
   GROUP BY f.produto_pai_id
), gates AS (
  SELECT p.*,
         (bom.produto_pai_id IS NOT NULL) AS tem_ficha,
         coalesce(bom.miolo,false) AS tem_miolo,
         coalesce(bom.capa,false) AS tem_capa,
         coalesce(bom.contra,false) AS tem_contra,
         coalesce(bom.acabamento,false) AS tem_acabamento,
         (NOT EXISTS (SELECT 1 FROM public.categoria_bom_regras r WHERE r.categoria_pai_id=p.categoria_id)
          OR NOT EXISTS (
            SELECT 1 FROM public.categoria_bom_regras r
             WHERE r.categoria_pai_id=p.categoria_id
               AND NOT EXISTS (
                 SELECT 1 FROM public.ficha_tecnica f
                 JOIN public.produtos c ON c.id=f.componente_id
                 JOIN public.categorias cc ON cc.id=c.categoria_id
                WHERE f.produto_pai_id=p.id
                  AND coalesce(cc.grupo_bom,f.grupo)=upper(r.nome_grupo)
               )
          )) AS ficha_completa,
         (coalesce(p.permite_arte,false) OR EXISTS (
            SELECT 1 FROM public.ficha_tecnica f JOIN public.produtos c ON c.id=f.componente_id
            JOIN public.categorias cc ON cc.id=c.categoria_id
            WHERE f.produto_pai_id=p.id AND cc.permite_arte
         )) AS exige_arte,
         (p.arte_confirmada_em IS NOT NULL) AS arte_confirmada,
         (p.parent_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.produto_pai_eixos pe
             WHERE pe.produto_pai_id=p.parent_id
               AND NOT EXISTS (SELECT 1 FROM public.produto_variacao_valores vv
                                WHERE vv.produto_id=p.id AND vv.eixo_id=pe.eixo_id)
         )) AS eixos_completos,
         EXISTS (SELECT 1 FROM public.produtos_externos e WHERE e.produto_id=p.id) AS tem_apelido_externo,
         (coalesce(p.preco_custo,0)>0) AS tem_custo,
         EXISTS (SELECT 1 FROM public.produto_anuncios a WHERE a.produto_id=p.id AND a.status='ativo') AS tem_anuncio
    FROM p LEFT JOIN bom ON bom.produto_pai_id=p.id
), resultado AS (
  SELECT g.*, array_remove(ARRAY[
    CASE WHEN NOT g.tem_ficha THEN 'sem ficha' END,
    CASE WHEN NOT g.ficha_completa THEN 'ficha incompleta' END,
    CASE WHEN g.exige_arte AND NOT g.arte_confirmada THEN 'arte não confirmada pelo agente' END,
    CASE WHEN NOT g.eixos_completos THEN 'eixos incompletos' END,
    CASE WHEN NOT g.tem_apelido_externo THEN 'sem apelido externo' END,
    CASE WHEN NOT g.tem_custo THEN 'sem custo' END
  ],NULL) AS pendencias
  FROM gates g
)
SELECT r.id,r.estagio,r.sku::text,r.nome::text,r.categoria_id,r.tem_ficha,r.tem_miolo,
       r.tem_capa,r.tem_contra,r.tem_acabamento,r.ficha_completa,r.exige_arte,
       r.arte_confirmada,r.eixos_completos,r.tem_apelido_externo,r.tem_custo,r.tem_anuncio,
       CASE WHEN cardinality(r.pendencias)=0 THEN 'PUBLICADO'::public.estagio_produto
            WHEN r.exige_arte AND NOT r.arte_confirmada THEN 'ARTE_PENDENTE'::public.estagio_produto
            WHEN NOT r.ficha_completa OR NOT r.eixos_completos THEN 'FICHA_OK'::public.estagio_produto
            WHEN NOT r.tem_apelido_externo OR NOT r.tem_anuncio THEN 'CANAL_OK'::public.estagio_produto
            ELSE 'RASCUNHO'::public.estagio_produto END,
       r.pendencias,
       coalesce((SELECT array_agg(t.nome ORDER BY t.nome) FROM public.produto_tags pt JOIN public.tags t ON t.id=pt.tag_id WHERE pt.produto_id=r.id),'{}'::text[])
  FROM resultado r;
$$;

CREATE OR REPLACE FUNCTION public.listar_produtos_prontidao(
  p_tag_id integer DEFAULT NULL, p_estagio public.estagio_produto DEFAULT NULL
)
RETURNS TABLE (
  produto_id integer, estagio public.estagio_produto, sku text, nome text,
  categoria_id integer, tem_ficha boolean, tem_miolo boolean, tem_capa boolean,
  tem_contra boolean, tem_acabamento boolean, ficha_completa boolean,
  exige_arte boolean, arte_confirmada boolean, eixos_completos boolean,
  tem_apelido_externo boolean, tem_custo boolean, tem_anuncio boolean,
  proximo_estagio public.estagio_produto, pendencias text[], tags text[]
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $$
  SELECT pp.* FROM public.produtos p
   CROSS JOIN LATERAL public.produto_prontidao(p.id) pp
   WHERE (p_tag_id IS NULL OR EXISTS (SELECT 1 FROM public.produto_tags pt WHERE pt.produto_id=pp.produto_id AND pt.tag_id=p_tag_id))
     AND (p_estagio IS NULL OR estagio=p_estagio)
  ORDER BY pp.produto_id;
$$;

CREATE OR REPLACE FUNCTION public.publicar_produto(p_produto_id integer)
RETURNS public.produtos LANGUAGE plpgsql SECURITY INVOKER SET search_path TO public AS $$
DECLARE r record; atualizado public.produtos;
BEGIN
  SELECT * INTO r FROM public.produto_prontidao(p_produto_id);
  IF NOT FOUND THEN RAISE EXCEPTION 'Produto % não encontrado', p_produto_id; END IF;
  IF cardinality(r.pendencias) > 0 THEN
    RAISE EXCEPTION 'Produto não pode ser publicado: %', array_to_string(r.pendencias, ', ');
  END IF;
  UPDATE public.produtos SET status='ativo', estagio='PUBLICADO', updated_at=now()
   WHERE id=p_produto_id RETURNING * INTO atualizado;
  RETURN atualizado;
END $$;

REVOKE ALL ON FUNCTION public.produto_prontidao(integer) FROM PUBLIC,anon;
REVOKE ALL ON FUNCTION public.listar_produtos_prontidao(integer,public.estagio_produto) FROM PUBLIC,anon;
REVOKE ALL ON FUNCTION public.publicar_produto(integer) FROM PUBLIC,anon;