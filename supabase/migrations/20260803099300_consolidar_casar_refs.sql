-- Casamento entre a planilha do marketplace e os pedidos canonicos da base.
--
-- A tela "Consolidar" recebe um arquivo exportado do painel do marketplace.
-- Antes, ela criava demanda direto do que estava no arquivo — um segundo lugar
-- onde a demanda nascia, e o unico que nao passava pela regra logistica: o
-- arquivo nao sabe a modalidade nem a janela de coleta do pedido. O resultado
-- era um lote que a Torre de Despacho nao reconhecia e um pedido que podia
-- entrar em duas demandas.
--
-- Agora o arquivo serve para CONFERIR: cada linha e casada com um pedido da
-- base pelo ID de origem, e o operador enxerga o que a base ja tem, o que ela
-- ainda nao tem, e em quais nos da torre aqueles pedidos caem. A demanda
-- continua nascendo em um lugar so.
--
-- O casamento tenta os dois campos que carregam o ID do marketplace, porque
-- eles divergem por canal: `marketplace_order_id` e preenchido pelo ingest via
-- API, e `codigo_pedido_externo` e o que vem do ERP (numeroLoja). Uma planilha
-- da Shopee traz o primeiro; uma exportacao passada pelo Bling costuma trazer
-- o segundo. Casar so por um deles fazia a metade do arquivo parecer "pedido
-- que a base nao tem" — a leitura mais cara possivel nesta tela, porque
-- convida o operador a reimportar o que ja existe.
CREATE OR REPLACE FUNCTION public.consolidar_casar_refs(p_refs text[])
RETURNS TABLE(
    ref                        text,
    pedido_id                  integer,
    numero_pedido              text,
    codigo_pedido_externo      text,
    marketplace_order_id       text,
    marketplace_integration_id integer,
    marketplace_nome           text,
    modalidade_logistica_id    integer,
    modalidade_nome            text,
    data_limite_envio          timestamp with time zone,
    situacao_pedido_id         integer,
    despachado_em              timestamp with time zone,
    na_torre                   boolean
)
LANGUAGE sql
STABLE
SET search_path TO 'public', 'pg_temp'
AS $function$
WITH refs AS (
    -- Deduplica preservando a grafia original: o operador procura no arquivo
    -- pelo que esta escrito nele, nao pela versao normalizada.
    SELECT DISTINCT
           btrim(r)            AS ref,
           upper(btrim(r))     AS chave
      FROM unnest(coalesce(p_refs, ARRAY[]::text[])) AS r
     WHERE btrim(coalesce(r, '')) <> ''
),
casado AS (
    SELECT r.ref,
           p.id,
           p.numero_pedido,
           p.codigo_pedido_externo,
           p.marketplace_order_id,
           p.marketplace_integration_id,
           p.modalidade_logistica_id,
           p.data_limite_envio,
           p.situacao_pedido_id,
           p.despachado_em,
           -- Empate e possivel quando dois pedidos compartilham o ID de origem
           -- (pacote). Fica com o mais recente: e o que o operador acabou de
           -- exportar do painel.
           row_number() OVER (PARTITION BY r.chave ORDER BY p.id DESC) AS posicao
      FROM refs r
      JOIN public.pedidos p
        ON upper(btrim(coalesce(p.marketplace_order_id, ''))) = r.chave
        OR upper(btrim(coalesce(p.codigo_pedido_externo, ''))) = r.chave
)
SELECT
    r.ref,
    c.id                                                        AS pedido_id,
    c.numero_pedido::text,
    c.codigo_pedido_externo::text,
    c.marketplace_order_id::text,
    c.marketplace_integration_id,
    coalesce(ii.instance_name, 'Origem nao resolvida')::text    AS marketplace_nome,
    c.modalidade_logistica_id,
    coalesce(m.nome, 'Modalidade não classificada')::text       AS modalidade_nome,
    c.data_limite_envio,
    c.situacao_pedido_id,
    c.despachado_em,
    -- na_torre responde a pergunta que decide o proximo clique: este pedido
    -- ainda pode entrar numa consolidacao? Um pedido ja despachado, cancelado
    -- ou preso a uma demanda publicada aparece casado (a base o tem) e fora da
    -- torre (nao entra em lote novo) — dizer so "encontrado" faria o operador
    -- procurar na torre por um pedido que nunca vai estar la.
    (v.id IS NOT NULL)                                          AS na_torre
  FROM refs r
  LEFT JOIN casado c
         ON c.ref = r.ref AND c.posicao = 1
  LEFT JOIN public.installed_integrations ii ON ii.id = c.marketplace_integration_id
  LEFT JOIN public.modalidades_logisticas  m ON m.id  = c.modalidade_logistica_id
  LEFT JOIN public.vw_pedidos_pendentes_despacho v ON v.id = c.id
 ORDER BY (c.id IS NULL) DESC, coalesce(ii.instance_name, ''), coalesce(m.nome, ''), r.ref;
$function$;

COMMENT ON FUNCTION public.consolidar_casar_refs(text[]) IS
'Casa IDs de origem de uma planilha do marketplace com pedidos canonicos. Usada pela tela Consolidar para conferir o arquivo contra a base antes de consolidar o lote na Torre de Despacho.';
