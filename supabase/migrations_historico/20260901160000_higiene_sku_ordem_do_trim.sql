-- Correcao da migration anterior: `btrim()` sem argumento remove ESPACO, nao
-- whitespace. Com `regexp_replace(btrim(sku), ...)` um SKU que comeca com
-- TABULACAO sobrevive: o btrim nao tira a tabulacao, o regexp a converte em
-- espaco, e o resultado fica com espaco a esquerda - para sempre diferente do
-- original. Sobraram 6 SKUs assim, todos comecando com tab.
--
-- A ordem correta e colapsar primeiro e aparar depois.
UPDATE public.produtos
   SET sku = btrim(regexp_replace(sku, '[[:space:]]+', ' ', 'g'))
 WHERE sku <> btrim(regexp_replace(sku, '[[:space:]]+', ' ', 'g'));

DROP INDEX IF EXISTS public.ux_produtos_sku_normalizado;

CREATE UNIQUE INDEX ux_produtos_sku_normalizado
  ON public.produtos ((upper(btrim(regexp_replace(sku, '[[:space:]]+', ' ', 'g')))));

COMMENT ON INDEX public.ux_produtos_sku_normalizado IS
  'SKU unico no espaco normalizado: colapsa qualquer whitespace (inclusive tabulacao) e so entao apara as pontas. Impede cadastrar ou editar um SKU para cima de outro que so difere por espaco, tabulacao ou caixa.';
