-- Torre de despacho: so pedido que ainda e trabalho do galpao.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## O bug
--
-- `despacho_arvore` e `despacho_escopo_pedidos` filtravam apenas
-- `despachado_em IS NULL`. Esse campo so passou a ser carimbado quando o fluxo
-- novo de lancamento entrou no ar, entao todo o historico anterior tem NULL —
-- independente de o pedido ja ter sido entregue, cancelado ou devolvido.
--
-- Resultado em 02/08/2026: 1529 pedidos Shopee na torre, dos quais apenas 174
-- estavam em situacao de producao. O resto era 663 entregues, 119 cancelados,
-- devolvidos, nao pagos e enviados.
--
-- O sintoma visivel era o contador errado. O risco real era o botao: o mesmo
-- predicado alimentava `despacho_escopo_pedidos`, entao "Conferir e lancar
-- (1000)" teria posto pedidos cancelados e ja entregues dentro de uma demanda
-- de producao — e carimbado `despachado_em` neles.
--
-- ## O criterio
--
-- `situacao_pedido_id IN (2, 3, 4)`: Em Andamento, Produzido, Pronto para
-- Envio. Fora ficam Em Aberto (1, ainda nao pago), Enviado (5), Entregue (6),
-- Cancelado (7) e Devolvido (8).
--
-- Nao usar `flag_cancelado` como negativa: isso deixaria Enviado e Entregue
-- dentro do escopo. A lista positiva diz o que e trabalho pendente, e e a
-- unica leitura que sobrevive a criacao de uma situacao nova.
--
-- Modalidades com `entra_na_torre = false` (Full) tambem saem: o marketplace
-- despacha, o galpao nao. Para o pedido Full ainda nao classificado, o fallback
-- e `pedidos.is_fulfillment`.
--
-- ## Invariante preservada
--
-- "A soma dos filhos e igual ao pai" continua valendo: o filtro age no `base`,
-- antes do GROUPING SETS, entao nenhum nivel enxerga um universo diferente do
-- outro. O predicado e literalmente identico nas duas funcoes de proposito —
-- se divergirem, a tela passa a prometer um total que o lancamento nao entrega.

CREATE OR REPLACE FUNCTION public.despacho_arvore(
    p_data date DEFAULT CURRENT_DATE
)
RETURNS TABLE (
    nivel                    smallint,
    integration_id           integer,
    marketplace_nome         text,
    modalidade_id            integer,
    modalidade_codigo        text,
    modalidade_nome          text,
    tipo_prazo               text,
    bucket_prazo             text,
    qtd_pedidos              integer,
    qtd_itens                integer,
    compromisso_mais_proximo timestamptz,
    ordem                    smallint
)
LANGUAGE sql
STABLE
AS $$
WITH base AS (
    SELECT
        p.id,
        p.marketplace_integration_id                       AS integration_id,
        COALESCE(ii.instance_name, 'Origem nao resolvida') AS marketplace_nome,
        p.modalidade_logistica_id                          AS modalidade_id,
        COALESCE(m.codigo, 'NAO_CLASSIFICADA')             AS modalidade_codigo,
        COALESCE(m.nome, 'Modalidade nao classificada')    AS modalidade_nome,
        COALESCE(m.tipo_prazo, 'FIXO')                     AS tipo_prazo,
        COALESCE(m.ordem_exibicao, 0)::smallint            AS ordem,
        CASE
            WHEN p.data_limite_envio IS NULL                             THEN 'sem_prazo'
            WHEN (p.data_limite_envio)::date <  p_data                   THEN 'atrasado'
            WHEN (p.data_limite_envio)::date =  p_data                   THEN 'hoje'
            WHEN (p.data_limite_envio)::date =  p_data + 1               THEN 'amanha'
            ELSE 'depois'
        END                                                AS bucket_prazo,
        p.compromisso_logistico_em,
        COALESCE(i.qtd, 0)                                 AS qtd_itens
      FROM public.pedidos p
      LEFT JOIN public.installed_integrations ii
             ON ii.id = p.marketplace_integration_id
      LEFT JOIN public.modalidades_logisticas m
             ON m.id = p.modalidade_logistica_id
      LEFT JOIN LATERAL (
            SELECT round(sum(ip.quantidade))::integer AS qtd
              FROM public.itens_pedido ip
             WHERE ip.pedido_id = p.id
      ) i ON true
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
)
SELECT
    (2 - grouping(b.modalidade_id) - grouping(b.bucket_prazo))::smallint AS nivel,
    b.integration_id,
    max(b.marketplace_nome)::text                                        AS marketplace_nome,
    CASE WHEN grouping(b.modalidade_id) = 0 THEN b.modalidade_id END     AS modalidade_id,
    CASE WHEN grouping(b.modalidade_id) = 0
         THEN max(b.modalidade_codigo)::text END                         AS modalidade_codigo,
    CASE WHEN grouping(b.modalidade_id) = 0
         THEN max(b.modalidade_nome)::text END                           AS modalidade_nome,
    CASE WHEN grouping(b.modalidade_id) = 0
         THEN max(b.tipo_prazo)::text END                                AS tipo_prazo,
    CASE WHEN grouping(b.bucket_prazo) = 0 THEN b.bucket_prazo END       AS bucket_prazo,
    count(*)::integer                                                    AS qtd_pedidos,
    COALESCE(sum(b.qtd_itens), 0)::integer                               AS qtd_itens,
    min(b.compromisso_logistico_em)                                      AS compromisso_mais_proximo,
    COALESCE(min(b.ordem), 0)::smallint                                  AS ordem
  FROM base b
 GROUP BY GROUPING SETS (
    (b.integration_id),
    (b.integration_id, b.modalidade_id),
    (b.integration_id, b.modalidade_id, b.bucket_prazo)
 )
 ORDER BY
    (2 - grouping(b.modalidade_id) - grouping(b.bucket_prazo)),
    min(b.compromisso_logistico_em) NULLS LAST,
    b.integration_id,
    COALESCE(min(b.ordem), 0),
    CASE
        WHEN grouping(b.bucket_prazo) = 1 THEN 0
        WHEN b.bucket_prazo = 'atrasado'  THEN 1
        WHEN b.bucket_prazo = 'hoje'      THEN 2
        WHEN b.bucket_prazo = 'amanha'    THEN 3
        WHEN b.bucket_prazo = 'depois'    THEN 4
        ELSE 5
    END;
$$;

COMMENT ON FUNCTION public.despacho_arvore(date) IS
  'Tres niveis de totalizadores em uma chamada. nivel 0 = marketplace, 1 = modalidade, 2 = prazo. Conta apenas pedido pendente de despacho (situacao 2/3/4) em modalidade que entra na torre. qtd_pedidos e a unidade de conferencia contra o painel da origem; qtd_itens e carga de producao.';

-- --------------------------------------------------------------------------
-- Escopo: mesmo predicado, palavra por palavra
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.despacho_escopo_pedidos(
    p_integration_id integer,
    p_modalidade_id  integer,
    p_horizonte      text[] DEFAULT ARRAY['atrasado', 'hoje'],
    p_data           date DEFAULT CURRENT_DATE
)
RETURNS SETOF integer
LANGUAGE sql
STABLE
AS $$
    SELECT p.id
      FROM public.pedidos p
      LEFT JOIN public.modalidades_logisticas m
             ON m.id = p.modalidade_logistica_id
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
       AND p.marketplace_integration_id IS NOT DISTINCT FROM p_integration_id
       AND p.modalidade_logistica_id    IS NOT DISTINCT FROM p_modalidade_id
       AND CASE
             WHEN p.data_limite_envio IS NULL               THEN 'sem_prazo'
             WHEN (p.data_limite_envio)::date <  p_data     THEN 'atrasado'
             WHEN (p.data_limite_envio)::date =  p_data     THEN 'hoje'
             WHEN (p.data_limite_envio)::date =  p_data + 1 THEN 'amanha'
             ELSE 'depois'
           END = ANY (p_horizonte)
     ORDER BY p.compromisso_logistico_em NULLS FIRST, p.id;
$$;

COMMENT ON FUNCTION public.despacho_escopo_pedidos(integer, integer, text[], date) IS
  'Predicado de pendencia identico ao de despacho_arvore: o total que a tela promete e o conjunto que o lancamento entrega. IS NOT DISTINCT FROM: NULL casa com NULL, para que "Origem nao resolvida" e "Modalidade nao classificada" sejam lancaveis como qualquer outro no.';

-- Indice parcial: a torre e recarregada a cada acao do operador.
CREATE INDEX IF NOT EXISTS idx_pedidos_despacho_pendente
    ON public.pedidos (marketplace_integration_id, modalidade_logistica_id, data_limite_envio)
 WHERE despachado_em IS NULL AND situacao_pedido_id IN (2, 3, 4);
