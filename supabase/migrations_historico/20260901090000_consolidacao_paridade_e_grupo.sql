-- Restaura a integridade da consolidacao de pedidos.
--
-- A migration 20260831210000 trocou, na CTE `expandidos`, o LEFT JOIN por um
-- JOIN em `public.produtos`. Item de pedido sem produto interno resolvido
-- (`produto_final IS NULL`) deixou de casar e passou a ser descartado da
-- consolidacao — sem erro, sem log, sem linha. Medido na base: 15.427 de
-- 16.310 itens (94,6%). A funcao original carregava um comentario dizendo
-- exatamente o contrario:
--
--   "Nenhum destes passos pode falhar o item: nao achar produto e um
--    resultado valido, nao um erro."
--
-- Esta migration devolve a consolidacao ao comportamento anterior, 1:1, e fixa
-- duas decisoes:
--
-- P1. NAO ha explosao automatica de kit na consolidacao. O kit aparece como
--     UMA linha, e quem decide explodi-lo e o operador, na previa editavel
--     (`despacho_editar_itens_demanda`). Explodir no SQL retirava do operador
--     justamente a linha que ele precisa ver para decidir, e foi o que motivou
--     o JOIN que quebrou o caminho de todos os outros itens.
--
-- P2. A ficha efetiva so muda de comportamento quando alguem declara um grupo.
--     Sem grupo declarado, a regra e byte a byte a de antes.

-- ---------------------------------------------------------------------------
-- 1. Ficha efetiva: precedencia correta e paridade estrita sem grupo
-- ---------------------------------------------------------------------------
--
-- C1. `coalesce(cat.grupo_bom, f.grupo)` invertia a precedencia definida em
--     PRODUCT_REFACTORING.md §4.5: a categoria vencia sobre a linha. Passa a
--     ser `coalesce(f.grupo, cat.grupo_bom)`.
--
--     A inversao importa neste catalogo: as categorias 3 (Capa/Contra pronta)
--     e 10 (Capa/Contra impressao) tem metade capa e metade contra dentro
--     (46/45 e 45/44 produtos). Classificar qualquer uma com um unico
--     `grupo_bom` faria uma variacao com capa propria suprimir tambem a
--     contra-capa herdada do pai.
--
-- C2. Sem grupo declarado, a funcao devolve exatamente o que a regra antiga
--     devolvia — o `else` de `bom_service.get_bom_for_produto` e o `CASE` de
--     `despacho_consolidar_pedidos`:
--       heranca ligada  -> ficha do PAI
--       heranca desligada -> ficha PROPRIA
--     O merge por grupo so entra em cena quando existe ao menos uma linha
--     propria COM grupo. Sem isso o merge virava uniao (pai + propria) e
--     dobrava miolo, capa, custo e baixa de estoque.
--
-- C3. A retaguarda por `sku_produto_pai` — viva em `bom_service` e no caminho
--     do miolo desde sempre — estava ausente da funcao. Volta.

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
    SELECT p.id, p.sku, p.parent_id,
           (p.parent_id IS NOT NULL AND coalesce(p.herdar_bom_pai, false)) AS herda
      FROM public.produtos p WHERE p.id = p_produto_id
  ),
  -- Linhas proprias: por id, ou pela retaguarda de SKU (C3).
  proprio AS (
    SELECT f.*, coalesce(f.grupo, cat.grupo_bom) AS grupo_efetivo
      FROM public.ficha_tecnica f
      CROSS JOIN produto pr
      LEFT JOIN public.produtos   c   ON c.id   = f.componente_id
      LEFT JOIN public.categorias cat ON cat.id = c.categoria_id
     WHERE f.produto_pai_id = pr.id
        OR (f.produto_pai_id IS NULL AND f.sku_produto_pai IS NOT NULL
            AND f.sku_produto_pai = pr.sku)
  ),
  grupos_proprios AS (
    SELECT DISTINCT grupo_efetivo FROM proprio WHERE grupo_efetivo IS NOT NULL
  ),
  -- O merge so vale quando ha grupo declarado (C2).
  modo AS (
    SELECT pr.herda AS herda,
           (pr.herda AND EXISTS (SELECT 1 FROM grupos_proprios)) AS merge_por_grupo
      FROM produto pr
  ),
  pai AS (
    SELECT f.*, coalesce(f.grupo, cat.grupo_bom) AS grupo_efetivo
      FROM public.ficha_tecnica f
      CROSS JOIN produto pr
      CROSS JOIN modo m
      LEFT JOIN public.produtos   c   ON c.id   = f.componente_id
      LEFT JOIN public.categorias cat ON cat.id = c.categoria_id
     WHERE m.herda AND f.produto_pai_id = pr.parent_id
       AND (NOT m.merge_por_grupo
            OR NOT EXISTS (
                 SELECT 1 FROM grupos_proprios g
                  WHERE g.grupo_efetivo = coalesce(f.grupo, cat.grupo_bom)
               ))
  ),
  linhas AS (
    -- Heranca ligada e sem grupo declarado: so a ficha do pai (legado).
    SELECT p.*, false AS herdada FROM proprio p
     CROSS JOIN modo m
     WHERE NOT m.herda OR m.merge_por_grupo
    UNION ALL
    SELECT p.*, true AS herdada FROM pai p
  )
  SELECT l.id, l.produto_pai_id, l.componente_id, l.quantidade_necessaria,
         l.unidade_medida, l.grupo_efetivo, l.herdada
    FROM linhas l
   WHERE l.componente_id IS NOT NULL
   ORDER BY l.id;
$$;

COMMENT ON FUNCTION public.bom_efetiva_produto(integer) IS
  'Ficha tecnica efetiva. Sem grupo declarado o resultado e identico a regra legada (heranca ligada = ficha do pai; desligada = ficha propria). O merge por grupo so age quando ha linha propria com grupo.';

-- ---------------------------------------------------------------------------
-- 2. Consolidacao: volta a nao descartar item nenhum
-- ---------------------------------------------------------------------------
-- Identica a versao anterior a 20260831210000, com uma unica diferenca: o
-- miolo sai de `bom_efetiva_produto` em vez da subconsulta inline, para que
-- Python e SQL leiam a ficha pela MESMA funcao. Com a paridade garantida em
-- (1), o resultado e o mesmo.

CREATE OR REPLACE FUNCTION public.despacho_consolidar_pedidos(p_pedido_ids integer[])
RETURNS TABLE(ordem integer, miolo text, miolo_chave text, miolo_rank integer,
              miolo_total numeric, titulo_anuncio text, sku_externo text,
              variacao text, quantidade numeric, produto_id integer,
              produto_nome text, id_produto_miolo integer, miolo_origem text,
              contabiliza_estoque boolean, pedidos_origem integer[], itens_origem integer[])
LANGUAGE sql STABLE SET search_path TO public, pg_temp AS $$
WITH cfg AS (
    SELECT coalesce((SELECT (valor #>> '{}') FROM public.configuracoes_aplicacao
                      WHERE nome = 'producao_miolos_category_id'), '6')::integer AS cat_miolo
),
base AS (
    SELECT ip.id AS item_id, ip.pedido_id,
           coalesce(nullif(btrim(ip.titulo_anuncio), ''),
                    nullif(btrim(ip.descricao), ''), '-')      AS titulo,
           coalesce(nullif(btrim(ip.sku_externo), ''), '-')    AS sku,
           coalesce(nullif(btrim(ip.variacao_externa), ''), '-') AS variacao,
           public.miolo_do_sku(ip.sku_externo)                 AS miolo_chave,
           ip.quantidade,
           ip.produto_id                                       AS produto_vinculado
      FROM public.itens_pedido ip
     WHERE ip.pedido_id = ANY(p_pedido_ids)
),
-- Resolucao oportunista do produto interno, do sinal mais forte para o mais
-- fraco. NENHUM destes passos pode falhar o item: nao achar produto e um
-- resultado valido, nao um erro.
resolvido AS (
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
),
com_bom AS (
    SELECT r.*, bom.componente_id AS miolo_produto_id, bom.componente_nome AS miolo_bom,
           p.nome AS produto_nome
      FROM resolvido r
      CROSS JOIN cfg
      LEFT JOIN public.produtos p ON p.id = r.produto_final
      LEFT JOIN LATERAL (
            SELECT c.id AS componente_id, c.nome AS componente_nome
              FROM public.bom_efetiva_produto(r.produto_final) ft
              JOIN public.produtos c ON c.id = ft.componente_id
             WHERE c.categoria_id = cfg.cat_miolo
             ORDER BY ft.id LIMIT 1
      ) bom ON r.produto_final IS NOT NULL
),
ranks AS (
    SELECT miolo_chave, sum(quantidade) AS total,
           row_number() OVER (ORDER BY sum(quantidade) DESC, miolo_chave)::integer AS rank
      FROM com_bom GROUP BY miolo_chave
),
linhas AS (
    SELECT cb.titulo, cb.sku, cb.variacao, cb.miolo_chave,
           sum(cb.quantidade) AS qtd,
           max(cb.miolo_bom) AS miolo_bom, max(cb.miolo_produto_id) AS miolo_produto_id,
           max(cb.produto_final) AS produto_id, max(cb.produto_nome) AS produto_nome,
           array_agg(DISTINCT cb.pedido_id) AS pedidos,
           array_agg(cb.item_id ORDER BY cb.item_id) AS itens
      FROM com_bom cb
     GROUP BY cb.titulo, cb.sku, cb.variacao, cb.miolo_chave
)
SELECT (row_number() OVER (ORDER BY r.rank, l.qtd DESC, l.sku, l.variacao))::integer,
       coalesce(l.miolo_bom, l.miolo_chave), l.miolo_chave, r.rank, r.total,
       l.titulo, l.sku, l.variacao, l.qtd, l.produto_id, l.produto_nome,
       l.miolo_produto_id,
       CASE WHEN l.miolo_bom IS NOT NULL THEN 'BOM' ELSE 'SKU' END,
       (l.produto_id IS NOT NULL), l.pedidos, l.itens
  FROM linhas l JOIN ranks r ON r.miolo_chave = l.miolo_chave
 ORDER BY r.rank, l.qtd DESC, l.sku, l.variacao;
$$;

COMMENT ON FUNCTION public.despacho_consolidar_pedidos(integer[]) IS
  'Consolidacao canonica do lote. Item sem produto interno resolvido continua virando linha (miolo pelo prefixo do SKU). Kit NAO e explodido aqui: a explosao e decisao do operador na previa.';
