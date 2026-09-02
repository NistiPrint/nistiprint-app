-- Recuperada de supabase_migrations.schema_migrations (versao aplicada
-- 20260831165409). Foi aplicada direto no banco e nunca teve arquivo: sem este
-- arquivo, ninguem consegue revisar nem reproduzir o que ela fez.
--
-- Alimenta aliases somente com relacoes ja confirmadas em itens_pedido.produto_id.
-- Nao altera itens de pedido, produtos ou aliases existentes.
--
-- NOTA: o `NOT EXISTS` abaixo usa '\\s+', que em arquivo .sql e o literal
-- barra-barra-s-mais, e nao whitespace (mesmo defeito de M1). Na pratica a
-- guarda comparou sem colapsar espaco interno. Mantido como aplicado para o
-- arquivo refletir o banco; a correcao vem na migration de higiene de SKU.
INSERT INTO public.produtos_externos
  (produto_id, codigo_externo, tipo, plataforma, metadados)
SELECT min(i.produto_id), i.sku_externo, 'SKU', NULL,
       jsonb_build_object(
         'origem', 'itens_pedido_produto_id',
         'itens_confirmacao', count(*)
       )
  FROM public.itens_pedido i
 WHERE i.produto_id IS NOT NULL
   AND i.sku_externo IS NOT NULL
   AND btrim(i.sku_externo) <> ''
 GROUP BY i.sku_externo
HAVING count(DISTINCT i.produto_id) = 1
   AND NOT EXISTS (
     SELECT 1
       FROM public.produtos_externos e
      WHERE e.plataforma IS NULL
        AND upper(regexp_replace(btrim(e.codigo_externo), '\\s+', ' ', 'g')) =
            upper(regexp_replace(btrim(i.sku_externo), '\\s+', ' ', 'g'))
   );
