-- Fila de cadastro: os codigos que aparecem em pedido e nao chegam a produto
-- interno nenhum. Alimenta a tela de kit e a de produtos faltantes.
--
-- A fila junta duas situacoes muito diferentes, e `chega_ao_miolo` as separa
-- porque a urgente afundava no meio da outra:
--
--   320 codigos (14.575 itens) chegam ao MIOLO pela heuristica de prefixo. A
--     fabrica sabe o que imprimir; falta o cadastro para o item contar estoque
--     e para a variacao deixar de ser texto.
--    86 codigos (854 itens) nao chegam a NADA — 15 deles com cara de combo.
--     A linha entra sem miolo. E esta a fila que precisa de cadastro AGORA.
--
-- Enquanto o combo nao for um produto (`formato = 'kit'`) com ficha de produtos
-- acabados, a consolidacao nao tem o que explodir (ver 20260901140000).
DROP FUNCTION IF EXISTS public.codigos_externos_sem_produto();

CREATE FUNCTION public.codigos_externos_sem_produto()
RETURNS TABLE (
  codigo text,
  itens bigint,
  unidades numeric,
  titulo_exemplo text,
  miolo_chave text,
  chega_ao_miolo boolean,
  parece_combo boolean,
  ultima_venda timestamp without time zone
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path TO public AS $fn$
  WITH agrupado AS (
    SELECT upper(btrim(ip.sku_externo)) AS codigo,
           count(*) AS itens,
           sum(ip.quantidade) AS unidades,
           max(coalesce(nullif(btrim(ip.titulo_anuncio), ''), ip.descricao)) AS titulo_exemplo,
           public.miolo_do_sku(max(ip.sku_externo)) AS miolo_chave,
           max(p.data_venda) AS ultima_venda
      FROM public.itens_pedido ip
      JOIN public.pedidos p ON p.id = ip.pedido_id
     WHERE ip.sku_externo IS NOT NULL AND btrim(ip.sku_externo) <> ''
       AND ip.produto_id IS NULL
     GROUP BY 1
  ), classificado AS (
    SELECT a.*,
           ((SELECT m.miolo_id FROM public.resolver_miolo_por_prefixo(a.codigo, NULL, true) m) IS NOT NULL) AS chega_ao_miolo
      FROM agrupado a
     WHERE public.resolver_produto_por_codigo(a.codigo) IS NULL
  )
  SELECT c.codigo, c.itens, c.unidades, c.titulo_exemplo, c.miolo_chave,
         c.chega_ao_miolo,
         (c.codigo LIKE 'CMB%' OR c.codigo LIKE 'KIT%' OR c.codigo LIKE 'COMBO%'),
         c.ultima_venda
    FROM classificado c
   ORDER BY c.chega_ao_miolo, c.itens DESC, c.codigo;
$fn$;

COMMENT ON FUNCTION public.codigos_externos_sem_produto() IS
  'Codigos de pedido que nao resolvem para produto interno. chega_ao_miolo=false e a fila urgente: a linha entra sem miolo. Fila de cadastro de combo e de produto faltante.';

GRANT EXECUTE ON FUNCTION public.codigos_externos_sem_produto() TO service_role, authenticated;
