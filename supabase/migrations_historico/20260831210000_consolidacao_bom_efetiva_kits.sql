-- F5: consolidação usa a BOM efetiva e explode kits em produtos acabados.
CREATE OR REPLACE FUNCTION public.despacho_consolidar_pedidos(p_pedido_ids integer[])
RETURNS TABLE(ordem integer, miolo text, miolo_chave text, miolo_rank integer,
              miolo_total numeric, titulo_anuncio text, sku_externo text,
              variacao text, quantidade numeric, produto_id integer,
              produto_nome text, id_produto_miolo integer, miolo_origem text,
              contabiliza_estoque boolean, pedidos_origem integer[], itens_origem integer[])
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH cfg AS (
  SELECT coalesce((SELECT (valor #>> '{}') FROM public.configuracoes_aplicacao
                    WHERE nome='producao_miolos_category_id'),'6')::integer AS cat_miolo
), base AS (
  SELECT ip.id item_id, ip.pedido_id,
         coalesce(nullif(btrim(ip.titulo_anuncio),''),nullif(btrim(ip.descricao),''),'-') titulo,
         coalesce(nullif(btrim(ip.sku_externo),''),'-') sku,
         coalesce(nullif(btrim(ip.variacao_externa),''),'-') variacao,
         public.miolo_do_sku(ip.sku_externo) miolo_chave, ip.quantidade,
         ip.produto_id produto_vinculado
    FROM public.itens_pedido ip WHERE ip.pedido_id=ANY(p_pedido_ids)
), resolvido AS (
  SELECT b.*, coalesce(b.produto_vinculado,pe.produto_id,pr.id) produto_final
    FROM base b
    LEFT JOIN LATERAL (
      SELECT x.produto_id FROM public.produtos_externos x
       WHERE b.produto_vinculado IS NULL AND upper(btrim(x.codigo_externo))=upper(b.sku)
       ORDER BY CASE x.tipo WHEN 'SKU' THEN 1 WHEN 'ID' THEN 2 ELSE 3 END,
                CASE WHEN x.plataforma IS NULL THEN 1 ELSE 0 END LIMIT 1
    ) pe ON true
    LEFT JOIN LATERAL (
      SELECT x.id FROM public.produtos x
       WHERE b.produto_vinculado IS NULL AND pe.produto_id IS NULL
         AND upper(btrim(x.sku))=upper(b.sku) LIMIT 1
    ) pr ON true
), expandidos AS (
  SELECT r.item_id,r.pedido_id,r.titulo,r.sku,r.variacao,r.miolo_chave,
         r.quantidade,r.produto_final produto_id
    FROM resolvido r JOIN public.produtos p ON p.id=r.produto_final
   WHERE p.formato IS DISTINCT FROM 'kit'
  UNION ALL
  SELECT r.item_id,r.pedido_id,r.titulo,r.sku,r.variacao,r.miolo_chave,
         r.quantidade * coalesce(ft.quantidade_necessaria,1), ft.componente_id
    FROM resolvido r JOIN public.produtos p ON p.id=r.produto_final
    JOIN LATERAL public.bom_efetiva_produto(r.produto_final) ft ON true
    JOIN public.produtos c ON c.id=ft.componente_id
   WHERE p.formato='kit' AND c.tipo_produto='PRODUTO_ACABADO'
), com_bom AS (
  SELECT e.*, b.miolo_produto_id, b.miolo_nome produto_nome_miolo,
         p.nome produto_nome
    FROM expandidos e CROSS JOIN cfg
    LEFT JOIN public.produtos p ON p.id=e.produto_id
    LEFT JOIN LATERAL (
      SELECT c.id miolo_produto_id,c.nome miolo_nome
        FROM public.bom_efetiva_produto(e.produto_id) ft
        JOIN public.produtos c ON c.id=ft.componente_id AND c.categoria_id=cfg.cat_miolo
       ORDER BY ft.id LIMIT 1
    ) b ON true
), ranks AS (
  SELECT miolo_chave,sum(quantidade) total,
         row_number() OVER (ORDER BY sum(quantidade) DESC,miolo_chave)::integer rank
    FROM com_bom GROUP BY miolo_chave
), linhas AS (
  SELECT cb.titulo,cb.sku,cb.variacao,cb.miolo_chave,sum(cb.quantidade) qtd,
         max(cb.produto_nome_miolo) miolo_bom,max(cb.miolo_produto_id) miolo_produto_id,
         max(cb.produto_id) produto_id,max(cb.produto_nome) produto_nome,
         array_agg(DISTINCT cb.pedido_id) pedidos,array_agg(cb.item_id ORDER BY cb.item_id) itens
    FROM com_bom cb GROUP BY cb.titulo,cb.sku,cb.variacao,cb.miolo_chave
)
SELECT row_number() OVER (ORDER BY r.rank,l.qtd DESC,l.sku,l.variacao)::integer,
       coalesce(l.miolo_bom,l.miolo_chave),l.miolo_chave,r.rank,r.total,l.titulo,l.sku,
       l.variacao,l.qtd,l.produto_id,l.produto_nome,l.miolo_produto_id,
       CASE WHEN l.miolo_bom IS NOT NULL THEN 'BOM' ELSE 'SKU' END,
       (l.produto_id IS NOT NULL),l.pedidos,l.itens
  FROM linhas l JOIN ranks r ON r.miolo_chave=l.miolo_chave
 ORDER BY r.rank,l.qtd DESC,l.sku,l.variacao;
$$;