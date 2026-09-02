-- Pacote do Mercado Livre: N pedidos canonicos, um unico pedido no ERP.
--
-- ## O crash
--
--     duplicate key value violates unique constraint "ux_pedidos_pedido_bling_id"
--     Key (pedido_bling_id)=(7814) already exists.
--
-- Pedidos 54311 (`...490678`) e 54312 (`...490680`) sao o mesmo pacote ML
-- (`pack_id` 2000013854279907). O Bling tem UM pedido para os dois, e a busca
-- por `numeroLoja` devolve esse mesmo pedido tanto pelo numero do pedido quanto
-- pelo numero do pacote. Os dois resolviam para o mesmo registro em
-- `pedidos_bling`, e o segundo esbarrava no indice unico.
--
-- ## O que o indice unico afirmava
--
-- `ux_pedidos_pedido_bling_id` codificava "um pedido canonico para um pedido do
-- ERP". Isso e verdade para venda avulsa e falso para pacote. Um pacote e uma
-- caixa: mesma etiqueta, mesma nota, mesmo envio — e varias linhas de venda no
-- marketplace. O indice nao estava protegendo uma invariante; estava negando
-- uma forma legitima de venda.
--
-- Trocado por indice comum (a busca por pedido_bling_id continua precisando de
-- indice) mais `pack_id`, que e o que de fato agrupa.
--
-- ## Consequencia assumida
--
-- Os irmaos passam a compartilhar `numero_pedido` (o numero do Bling). Duas
-- linhas com o mesmo numero na lista de pedidos e desconfortavel, mas e a
-- verdade operacional: sao um envio so. `pack_id` existe para a tela poder
-- agrupa-las em vez de parecerem duplicatas.

ALTER TABLE public.pedidos
    ADD COLUMN IF NOT EXISTS pack_id text;

COMMENT ON COLUMN public.pedidos.pack_id IS
  'Identificador do pacote na origem (ML pack_id). Pedidos com o mesmo pack_id vao na mesma caixa e compartilham um unico pedido no ERP.';

DROP INDEX IF EXISTS public.ux_pedidos_pedido_bling_id;

CREATE INDEX IF NOT EXISTS ix_pedidos_pedido_bling_id
    ON public.pedidos (pedido_bling_id) WHERE pedido_bling_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_pedidos_pack_id
    ON public.pedidos (pack_id) WHERE pack_id IS NOT NULL;

-- Backfill a partir do payload cru. 146 pedidos tem pack_id; 4 pacotes tem mais
-- de um pedido — os quatro que iam quebrar a fila, um de cada vez.
UPDATE public.pedidos p
   SET pack_id = ml.pack
  FROM (
    SELECT codigo_pedido, NULLIF(btrim(raw_order->>'pack_id'), '') AS pack
      FROM public.pedidos_mercadolivre
  ) ml
 WHERE p.marketplace_order_id = ml.codigo_pedido
   AND ml.pack IS NOT NULL
   AND p.pack_id IS DISTINCT FROM ml.pack;
