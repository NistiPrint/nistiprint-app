-- Usa o codigo operacional do miolo na coluna Miolos das demandas.

BEGIN;

UPDATE public.itens_demanda
SET miolo_nome = btrim(miolo_chave)
WHERE nullif(btrim(miolo_chave), '') IS NOT NULL
  AND miolo_nome IS DISTINCT FROM btrim(miolo_chave);

CREATE OR REPLACE FUNCTION public.despacho_consolidar_pedidos(p_pedido_ids integer[])
RETURNS TABLE(ordem integer, miolo text, miolo_chave text, miolo_rank integer,
              miolo_total numeric, titulo_anuncio text, sku_externo text,
              variacao text, quantidade numeric, produto_id integer,
              produto_nome text, id_produto_miolo integer, miolo_origem text,
              contabiliza_estoque boolean, pedidos_origem integer[],
              itens_origem integer[])
LANGUAGE sql STABLE
SET search_path TO public, pg_temp
AS $function$
WITH cfg AS (
    SELECT coalesce((SELECT (valor #>> '{}')
                       FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_miolos_category_id'), '6')::integer AS cat_miolo
), base AS (
    SELECT ip.id AS item_id, ip.pedido_id,
           coalesce(nullif(btrim(ip.titulo_anuncio), ''), nullif(btrim(ip.descricao), ''), '-') AS titulo,
           coalesce(nullif(btrim(ip.sku_externo), ''), '-') AS sku,
           coalesce(nullif(btrim(ip.variacao_externa), ''), '-') AS variacao,
           public.miolo_do_sku(ip.sku_externo) AS miolo_chave,
           ip.quantidade, ip.produto_id AS produto_vinculado
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = ANY(p_pedido_ids)
), resolvido AS (
    SELECT b.*, coalesce(b.produto_vinculado, pe.produto_id, pr.id) AS produto_final
      FROM base b
      LEFT JOIN LATERAL (
        SELECT x.produto_id FROM public.produtos_externos x
         WHERE b.produto_vinculado IS NULL
           AND upper(btrim(x.codigo_externo)) = upper(b.sku)
         ORDER BY CASE x.tipo WHEN 'SKU' THEN 1 WHEN 'ID' THEN 2 ELSE 3 END,
                  CASE WHEN x.plataforma IS NULL THEN 1 ELSE 0 END
         LIMIT 1
      ) pe ON true
      LEFT JOIN LATERAL (
        SELECT x.id FROM public.produtos x
         WHERE b.produto_vinculado IS NULL AND pe.produto_id IS NULL
           AND upper(btrim(x.sku)) = upper(b.sku)
         LIMIT 1
      ) pr ON true
), kit_componentes AS (
    SELECT k.produto_id AS kit_id, c.*
      FROM (SELECT DISTINCT r.produto_final AS produto_id
              FROM resolvido r JOIN public.produtos p ON p.id = r.produto_final
             WHERE p.formato = 'kit') k
      CROSS JOIN LATERAL public.despacho_kit_componentes(k.produto_id) c
), expandido AS (
    SELECT r.item_id, r.pedido_id, r.titulo, r.sku, r.variacao,
           r.miolo_chave, r.quantidade, r.produto_final, false AS de_kit
      FROM resolvido r
     WHERE NOT EXISTS (SELECT 1 FROM kit_componentes kc WHERE kc.kit_id = r.produto_final)
    UNION ALL
    SELECT r.item_id, r.pedido_id, kc.nome, kc.sku, '-',
           coalesce(kc.miolo_chave, r.miolo_chave),
           r.quantidade * coalesce(kc.quantidade, 1), kc.produto_id, true
      FROM resolvido r JOIN kit_componentes kc ON kc.kit_id = r.produto_final
), com_bom AS (
    SELECT e.*, bom.componente_id AS miolo_produto_id,
           bom.componente_nome AS miolo_bom, p.nome AS produto_nome
      FROM expandido e CROSS JOIN cfg
      LEFT JOIN public.produtos p ON p.id = e.produto_final
      LEFT JOIN LATERAL (
        SELECT c.id AS componente_id, c.nome AS componente_nome
          FROM public.bom_efetiva_produto(e.produto_final) ft
          JOIN public.produtos c ON c.id = ft.componente_id
         WHERE c.categoria_id = cfg.cat_miolo
         ORDER BY ft.id LIMIT 1
      ) bom ON e.produto_final IS NOT NULL
), ranks AS (
    SELECT miolo_chave, sum(quantidade) AS total,
           row_number() OVER (ORDER BY sum(quantidade) DESC, miolo_chave)::integer AS rank
      FROM com_bom GROUP BY miolo_chave
), linhas AS (
    SELECT cb.titulo, cb.sku, cb.variacao, cb.miolo_chave,
           sum(cb.quantidade) AS qtd, max(cb.miolo_bom) AS miolo_bom,
           max(cb.miolo_produto_id) AS miolo_produto_id,
           max(cb.produto_final) AS produto_id, max(cb.produto_nome) AS produto_nome,
           array_agg(DISTINCT cb.pedido_id) AS pedidos,
           array_agg(DISTINCT cb.item_id) AS itens
      FROM com_bom cb
     GROUP BY cb.titulo, cb.sku, cb.variacao, cb.miolo_chave
)
SELECT row_number() OVER (ORDER BY r.rank, l.qtd DESC, l.sku, l.variacao, l.titulo)::integer,
       coalesce(l.miolo_chave, l.miolo_bom), l.miolo_chave, r.rank, r.total,
       l.titulo, l.sku, l.variacao, l.qtd, l.produto_id, l.produto_nome,
       l.miolo_produto_id,
       CASE WHEN l.miolo_bom IS NOT NULL THEN 'BOM' ELSE 'SKU' END,
       (l.produto_id IS NOT NULL), l.pedidos, l.itens
  FROM linhas l JOIN ranks r ON r.miolo_chave = l.miolo_chave
 ORDER BY r.rank, l.qtd DESC, l.sku, l.variacao, l.titulo;
$function$;

COMMIT;
