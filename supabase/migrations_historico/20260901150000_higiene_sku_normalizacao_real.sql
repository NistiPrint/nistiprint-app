-- M1: o indice unico de SKU nao normalizava espaco interno.
--
-- Em arquivo .sql, '\\s+' e o literal barra-barra-s-mais, nao whitespace:
-- `regexp_replace('A  B', '\\s+', ' ', 'g')` devolve 'A  B' inalterado. O indice
-- criado em 20260831150000 so fazia upper(btrim()), e a limpeza dos SKUs
-- prometida na F0.3 nunca rodou - 78 SKUs ainda tinham espaco sobrando nas
-- pontas ou espaco duplo no meio, alguns comecando com TABULACAO.
--
-- O UPDATE dispara `registrar_alteracao_sku`, que e o comportamento desejado:
-- cada SKU antigo fica em produto_sku_historico E vira apelido em
-- produtos_externos. Um pedido que chegar com o valor antigo continua casando.
-- Verificado antes de aplicar: 0 colisoes no espaco normalizado.
UPDATE public.produtos
   SET sku = regexp_replace(btrim(sku), '[[:space:]]+', ' ', 'g')
 WHERE sku <> regexp_replace(btrim(sku), '[[:space:]]+', ' ', 'g');

DROP INDEX IF EXISTS public.ux_produtos_sku_normalizado;

CREATE UNIQUE INDEX ux_produtos_sku_normalizado
  ON public.produtos ((upper(regexp_replace(btrim(sku), '[[:space:]]+', ' ', 'g'))));

-- A mesma armadilha estava na guarda de 20260831175000, que comparava apelidos
-- com o regex literal. Remove o apelido duplicado no espaco normalizado,
-- mantendo o mais antigo.
DELETE FROM public.produtos_externos e
 WHERE e.plataforma IS NULL
   AND EXISTS (
     SELECT 1 FROM public.produtos_externos o
      WHERE o.plataforma IS NULL
        AND o.produto_id = e.produto_id
        AND o.id < e.id
        AND upper(regexp_replace(btrim(o.codigo_externo), '[[:space:]]+', ' ', 'g')) =
            upper(regexp_replace(btrim(e.codigo_externo), '[[:space:]]+', ' ', 'g'))
   );
