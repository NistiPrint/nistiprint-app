-- Esteira FIFO das modalidades de prazo relativo (Turbo).
-- Contrato: docs/specs/02-domains/despacho/spec.md, "Modalidades de prazo relativo"
--
-- Alimenta a faixa de alerta no topo da aplicacao e, quando existir, a tela
-- `/despacho/esteira`. Uma RPC so para as duas: a faixa e a tela mostram a
-- mesma fila, e duas consultas diferentes acabariam mostrando ordens
-- diferentes para o mesmo operador.
--
-- Nao usa `despacho_arvore`: a torre e um totalizador acumulavel por prazo do
-- dia, e prazo relativo nao acumula em bucket de dia. Sao dois modelos de
-- tempo (ver 20260803091000).

CREATE OR REPLACE FUNCTION public.despacho_esteira_relativo()
RETURNS TABLE (
    pedido_id             integer,
    numero_pedido         text,
    marketplace_nome      text,
    modalidade_id         integer,
    modalidade_nome       text,
    modalidade_cor        text,
    nivel_interrupcao     smallint,
    data_venda            timestamptz,
    compromisso_em        timestamptz,
    minutos_restantes     integer,
    atrasado              boolean
)
LANGUAGE sql
STABLE
AS $fn$
    SELECT
        p.id,
        p.numero_pedido::text,
        COALESCE(ii.instance_name, 'Origem nao resolvida')::text,
        m.id,
        m.nome::text,
        m.cor::text,
        m.nivel_interrupcao,
        (p.data_venda AT TIME ZONE 'America/Sao_Paulo'),
        p.compromisso_logistico_em,
        -- floor, nao round: 39,7 minutos restantes e "39", nunca "40".
        -- Arredondar para cima um prazo regressivo devolve tempo que nao existe.
        floor(EXTRACT(epoch FROM (p.compromisso_logistico_em - now())) / 60)::integer,
        (p.compromisso_logistico_em <= now())
      FROM public.pedidos p
      JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
      LEFT JOIN public.installed_integrations ii ON ii.id = p.marketplace_integration_id
     WHERE m.tipo_prazo = 'RELATIVO'
       AND p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
     -- FIFO por prazo, nao por chegada: o pedido que vence primeiro sai
     -- primeiro, mesmo que tenha entrado depois.
     ORDER BY p.compromisso_logistico_em NULLS FIRST, p.id;
$fn$;

COMMENT ON FUNCTION public.despacho_esteira_relativo() IS
  'Fila FIFO das modalidades de prazo relativo (Turbo), ordenada por tempo ate o compromisso. Alimenta a faixa de alerta e a tela da esteira.';

GRANT EXECUTE ON FUNCTION public.despacho_esteira_relativo() TO anon, authenticated;
