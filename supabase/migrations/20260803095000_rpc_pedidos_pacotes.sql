-- Irmaos de pacote dos pedidos exibidos numa tela.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- Depois de 20260803092000, os pedidos de um mesmo pacote compartilham
-- `numero_pedido` (o numero do ERP). Isso e a verdade — sao um envio so — mas
-- na tela vira duas linhas com o mesmo numero, e a leitura natural disso e
-- "duplicata". A reacao natural a uma duplicata, momentos antes de lancar
-- producao, e remover uma das linhas: metade da caixa ficaria de fora.
--
-- RPC separada, e nao colunas novas em `list_pedidos_filtrados`, por uma razao
-- pratica: aquela funcao tem 174 linhas e e o caminho quente da tela de
-- pedidos. Uma chamada extra por pagina, sobre os ids ja carregados, custa
-- menos que reescreve-la — e falha de forma isolada, porque o marcador e
-- contexto, nao dado critico.

CREATE OR REPLACE FUNCTION public.pedidos_pacotes(p_pedido_ids bigint[])
RETURNS TABLE (
    pedido_id      bigint,
    pack_id        text,
    irmaos         integer,
    irmaos_ids     bigint[],
    irmaos_numeros text[]
)
LANGUAGE sql
STABLE
AS $fn$
    SELECT
        p.id,
        p.pack_id,
        (pk.total - 1)::integer,
        pk.ids,
        pk.numeros
      FROM public.pedidos p
      JOIN LATERAL (
            SELECT count(*) AS total,
                   array_agg(irmao.id ORDER BY irmao.id) FILTER (WHERE irmao.id <> p.id) AS ids,
                   array_agg(irmao.marketplace_order_id ORDER BY irmao.id)
                     FILTER (WHERE irmao.id <> p.id) AS numeros
              FROM public.pedidos irmao
             WHERE irmao.pack_id = p.pack_id
      ) pk ON true
     WHERE p.id = ANY (p_pedido_ids)
       AND p.pack_id IS NOT NULL
       -- Pacote de um pedido so nao e pacote: nao ha nada para agrupar, e um
       -- marcador nesse caso seria ruido em 138 dos 146 pedidos com pack_id.
       AND pk.total > 1;
$fn$;

COMMENT ON FUNCTION public.pedidos_pacotes(bigint[]) IS
  'Irmaos de pacote dos pedidos informados. Devolve apenas pacotes com mais de um pedido — os que compartilham numero_pedido e pareceriam duplicatas na tela.';

GRANT EXECUTE ON FUNCTION public.pedidos_pacotes(bigint[]) TO anon, authenticated;
