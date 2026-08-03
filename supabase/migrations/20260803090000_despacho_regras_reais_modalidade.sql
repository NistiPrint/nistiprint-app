-- Classificacao de modalidade: regras com os identificadores reais de producao,
-- alvo de fallback canonico e catalogo completo por marketplace.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## Por que esta migration existe
--
-- O seed 20260802100003 deixou COMUM e FLEX sem regra de proposito, esperando
-- que `metodos_envio_observados` revelasse os `logistics_channel_id` reais. A
-- deteccao nunca rodou, por um motivo simples: `_extract_shopee` procurava
-- `logistics_channel_id` na raiz do detalhe, e a Shopee entrega o campo dentro
-- de `package_list[]`. Com a chave sempre NULL, `classify_pedido` retornava
-- antes de tocar o banco e 100% dos pedidos caiam em "Modalidade nao
-- classificada" — inclusive Flex e Comum, que sao o volume inteiro.
--
-- Os IDs abaixo nao sao suposicao: sairam da varredura de `pedido_snapshots`
-- em producao (6235 pedidos Shopee, 359 ML). Ver comentario de cada regra.
--
-- ## Chave estavel vence rotulo, rotulo vence canonico
--
-- Tres alvos, avaliados por prioridade crescente:
--
--   CHAVE  (10..99)   logistics_channel_id / logistic_type. Identificador
--                     estavel da plataforma. Fonte primaria.
--   ROTULO (900)      shipping_carrier. Defensivo: canal novo com nome
--                     conhecido nao fica sem prazo enquanto ninguem cadastra.
--   CANONICA (950)
--                     `pedidos.modalidade_logistica`, derivado por
--                     `logistics_canonicalization`. Ultimo recurso, para o
--                     historico anterior a correcao do extrator e para pedidos
--                     ingeridos via Bling, que nao carregam package_list.
--
-- O alvo canonico e deliberadamente o menos confiavel dos tres, e a varredura
-- mostra por que: a canonicalizacao rotulou como STANDARD 38 pedidos de
-- Retirada pelo Comprador e 2 de Entrega Turbo. A chave estavel acertou os 40.
-- Onde os dois discordam, a prioridade garante que a chave ganhe.
--
-- ## Desvio consciente da spec
--
-- A spec diz: "Um metodo de envio desconhecido nunca e classificado como Comum
-- ou STANDARD por omissao". A regra CANONICA de STANDARD -> COMUM
-- viola isso, porque `logistics_canonicalization` grava STANDARD tambem quando
-- nao reconhece sinal nenhum ("STANDARD por omissao"). Decisao tomada com o
-- operador em 02/08/2026: o custo de um pedido Comum aparecer como nao
-- classificado e maior que o de um pedido exotico aparecer como Comum, porque
-- o primeiro caso e o volume e o segundo e a excecao. A regra fica em
-- prioridade 950 justamente para so agir quando nada melhor casou, e
-- `metodos_envio_observados` continua registrando o valor cru para o
-- cadastro correto ser feito depois.

-- --------------------------------------------------------------------------
-- 1. Novo alvo de regra
-- --------------------------------------------------------------------------

ALTER TABLE public.regras_classificacao_modalidade
    DROP CONSTRAINT IF EXISTS regras_classificacao_modalidade_alvo_check;

ALTER TABLE public.regras_classificacao_modalidade
    ADD CONSTRAINT regras_classificacao_modalidade_alvo_check
    CHECK (alvo::text IN ('CHAVE', 'ROTULO', 'CANONICA'));

-- --------------------------------------------------------------------------
-- 2. Modalidade que nao e trabalho do galpao
-- --------------------------------------------------------------------------
-- Full / fulfillment e despachado pelo proprio marketplace. Contar esses
-- pedidos na torre inflaria o numero de conferencia com trabalho que nunca
-- vai para producao. Marcar no cadastro, e nao com um `if codigo = 'FULL'` no
-- SQL da arvore, mantem a promessa de "cadastrar modalidade nao exige deploy".

ALTER TABLE public.modalidades_logisticas
    ADD COLUMN IF NOT EXISTS entra_na_torre boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN public.modalidades_logisticas.entra_na_torre IS
  'false para modalidades despachadas pelo proprio marketplace (Full). O pedido continua classificado e visivel no detalhe; apenas nao entra no contador de conferencia da torre nem no escopo de lancamento.';

-- --------------------------------------------------------------------------
-- 3. Catalogo: completar Shopee e criar Mercado Livre
-- --------------------------------------------------------------------------
-- ATENCAO: `corte_horario` e `coleta_horario` do Mercado Livre sao
-- provisorios, espelhados da Shopee por falta de dado confirmado. Confirmar
-- por conta em `modalidade_config_conta` antes de confiar no compromisso
-- calculado. O agrupamento em si nao depende desses valores.

INSERT INTO public.modalidades_logisticas (
    module_id, codigo, nome, tipo_prazo, politica_lote, nivel_interrupcao,
    corte_horario, coleta_horario, coleta_dia_offset,
    offset_etiqueta_min, offset_coleta_min, cor, ordem_exibicao, entra_na_torre
) VALUES
    ('shopee', 'RETIRADA', 'Retirada pelo Comprador', 'FIXO', 'LOTE', 0,
     '18:00', '08:00', 1, NULL, NULL, '#2F7A6B', 40, true),
    ('shopee', 'FULL', 'Full', 'FIXO', 'LOTE', 0,
     '23:59', NULL, 0, NULL, NULL, '#8B8B8B', 90, false),

    ('mercadolivre', 'COMUM', 'Comum', 'FIXO', 'LOTE', 0,
     '18:00', '08:00', 1, NULL, NULL, '#5F5E5A', 30, true),
    ('mercadolivre', 'FLEX', 'Flex', 'FIXO', 'LOTE', 0,
     '12:00', '13:00', 0, NULL, NULL, '#BA7517', 20, true),
    ('mercadolivre', 'FULL', 'Full', 'FIXO', 'LOTE', 0,
     '23:59', NULL, 0, NULL, NULL, '#8B8B8B', 90, false)
ON CONFLICT (module_id, codigo) DO NOTHING;

UPDATE public.modalidades_logisticas
   SET entra_na_torre = false
 WHERE codigo = 'FULL';

-- --------------------------------------------------------------------------
-- 4. Regras por chave estavel
-- --------------------------------------------------------------------------
-- Origem dos valores: varredura de pedido_snapshots em 02/08/2026.
--
--   Shopee  package_list[0].logistics_channel_id
--     91003  Shopee Xpress              4571 pedidos  -> COMUM
--     91007  Full                       1010          -> FULL
--     90033  Entrega Rapida              601          -> FLEX
--     90024  Retirada pelo Comprador      51          -> RETIRADA
--     90011  Entrega Turbo                 2          -> TURBO (ja cadastrado)
--
--   Mercado Livre  shipment.logistic.type / shipment.logistic_type
--     xd_drop_off   242 pedidos  -> COMUM
--     fulfillment    51          -> FULL
--     self_service   41          -> FLEX

CREATE TEMP TABLE _regras_seed (
    module_id     text,
    codigo        text,
    campo_origem  text,
    alvo          text,
    operador      text,
    valor         text,
    prioridade    integer
) ON COMMIT DROP;

INSERT INTO _regras_seed VALUES
    ('shopee', 'COMUM',    'logistics_channel_id', 'CHAVE', 'IGUAL', '91003', 10),
    ('shopee', 'FULL',     'logistics_channel_id', 'CHAVE', 'IGUAL', '91007', 10),
    ('shopee', 'FLEX',     'logistics_channel_id', 'CHAVE', 'IGUAL', '90033', 10),
    ('shopee', 'RETIRADA', 'logistics_channel_id', 'CHAVE', 'IGUAL', '90024', 10),

    ('mercadolivre', 'COMUM', 'logistic.type', 'CHAVE', 'IGUAL', 'xd_drop_off',  10),
    ('mercadolivre', 'FULL',  'logistic.type', 'CHAVE', 'IGUAL', 'fulfillment',  10),
    ('mercadolivre', 'FLEX',  'logistic.type', 'CHAVE', 'IGUAL', 'self_service', 10),

    -- Defensivas por rotulo. Canal novo com nome conhecido nao fica sem prazo.
    ('shopee', 'FLEX',     'shipping_carrier', 'ROTULO', 'CONTEM', 'Entrega Rapida',          900),
    ('shopee', 'FLEX',     'shipping_carrier', 'ROTULO', 'CONTEM', 'Entrega Rápida',          900),
    ('shopee', 'COMUM',    'shipping_carrier', 'ROTULO', 'CONTEM', 'Shopee Xpress',           900),
    ('shopee', 'RETIRADA', 'shipping_carrier', 'ROTULO', 'CONTEM', 'Retirada pelo Comprador', 900),

    -- Ultimo recurso. Ver "Desvio consciente da spec" no topo do arquivo.
    ('shopee', 'COMUM',    'modalidade_logistica', 'CANONICA', 'IGUAL', 'STANDARD',    950),
    ('shopee', 'FLEX',     'modalidade_logistica', 'CANONICA', 'IGUAL', 'FLEX',        950),
    ('shopee', 'FLEX',     'modalidade_logistica', 'CANONICA', 'IGUAL', 'EXPRESS',     950),
    ('shopee', 'FULL',     'modalidade_logistica', 'CANONICA', 'IGUAL', 'FULFILLMENT', 950),
    ('shopee', 'RETIRADA', 'modalidade_logistica', 'CANONICA', 'IGUAL', 'RETIRADA',    950),

    ('mercadolivre', 'COMUM', 'modalidade_logistica', 'CANONICA', 'IGUAL', 'STANDARD',    950),
    ('mercadolivre', 'FLEX',  'modalidade_logistica', 'CANONICA', 'IGUAL', 'FLEX',        950),
    ('mercadolivre', 'FLEX',  'modalidade_logistica', 'CANONICA', 'IGUAL', 'EXPRESS',     950),
    ('mercadolivre', 'FULL',  'modalidade_logistica', 'CANONICA', 'IGUAL', 'FULFILLMENT', 950);

INSERT INTO public.regras_classificacao_modalidade (
    module_id, modalidade_id, campo_origem, alvo, operador, valor, prioridade
)
SELECT s.module_id, m.id, s.campo_origem, s.alvo, s.operador, s.valor, s.prioridade
  FROM _regras_seed s
  JOIN public.modalidades_logisticas m
    ON m.module_id = s.module_id AND m.codigo = s.codigo
 WHERE NOT EXISTS (
     SELECT 1 FROM public.regras_classificacao_modalidade r
      WHERE r.module_id = s.module_id
        AND r.modalidade_id = m.id
        AND r.alvo  = s.alvo
        AND r.valor = s.valor
 );

-- --------------------------------------------------------------------------
-- 5. Classificador: resolver o alvo canonico
-- --------------------------------------------------------------------------
-- Duas mudancas em relacao a versao anterior:
--
--   a) o terceiro alvo, lido de `pedidos.modalidade_logistica`;
--   b) `compromisso_logistico_em` deixa de ser sobrescrito quando a
--      classificacao nao resolve nada. Antes, um pedido ja classificado que
--      passasse por aqui de novo sem chave perdia o compromisso e ia para o
--      fim da ordenacao canonica.

CREATE OR REPLACE FUNCTION public.classificar_pedido_modalidade(
    p_pedido_id integer,
    p_agora     timestamptz DEFAULT now()
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_integration_id integer;
    v_module_id      varchar(100);
    v_chave          text;
    v_rotulo         text;
    v_canonica       text;
    v_data_venda     timestamptz;
    v_regra_id       integer;
    v_modalidade_id  integer;
BEGIN
    SELECT p.marketplace_integration_id,
           p.marketplace_module_id,
           p.metodo_envio_chave,
           p.metodo_envio_rotulo,
           p.modalidade_logistica,
           p.data_venda AT TIME ZONE 'America/Sao_Paulo'
      INTO v_integration_id, v_module_id, v_chave, v_rotulo, v_canonica, v_data_venda
      FROM public.pedidos p
     WHERE p.id = p_pedido_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF v_module_id IS NOT NULL THEN
        SELECT r.id, r.modalidade_id
          INTO v_regra_id, v_modalidade_id
          FROM public.regras_classificacao_modalidade r
          JOIN public.modalidades_logisticas m ON m.id = r.modalidade_id AND m.ativo
         CROSS JOIN LATERAL (
            SELECT CASE r.alvo
                     WHEN 'ROTULO'              THEN v_rotulo
                     WHEN 'CANONICA' THEN v_canonica
                     ELSE v_chave
                   END AS alvo_valor
         ) a
         WHERE r.ativo
           AND r.module_id = v_module_id
           AND (r.integration_id IS NULL OR r.integration_id = v_integration_id)
           AND a.alvo_valor IS NOT NULL
           AND CASE r.operador
                 WHEN 'IGUAL' THEN
                     CASE WHEN r.case_sensitive
                          THEN a.alvo_valor = r.valor
                          ELSE lower(a.alvo_valor) = lower(r.valor) END
                 WHEN 'CONTEM' THEN
                     CASE WHEN r.case_sensitive
                          THEN position(r.valor in a.alvo_valor) > 0
                          ELSE position(lower(r.valor) in lower(a.alvo_valor)) > 0 END
                 WHEN 'PREFIXO' THEN
                     CASE WHEN r.case_sensitive
                          THEN a.alvo_valor LIKE r.valor || '%'
                          ELSE lower(a.alvo_valor) LIKE lower(r.valor) || '%' END
                 WHEN 'REGEX' THEN
                     CASE WHEN r.case_sensitive
                          THEN a.alvo_valor ~ r.valor
                          ELSE a.alvo_valor ~* r.valor END
                 ELSE false
               END
         ORDER BY (r.integration_id IS NULL), r.prioridade, r.id
         LIMIT 1;
    END IF;

    -- Nada casou: nao apagar uma classificacao anterior nem o compromisso.
    -- Reclassificar e refinar, nunca regredir.
    IF v_modalidade_id IS NULL THEN
        UPDATE public.pedidos
           SET modalidade_classificada_em = p_agora
         WHERE id = p_pedido_id;
        RETURN NULL;
    END IF;

    UPDATE public.pedidos
       SET modalidade_logistica_id    = v_modalidade_id,
           modalidade_regra_id        = v_regra_id,
           modalidade_classificada_em = p_agora,
           compromisso_logistico_em   = public.resolver_compromisso_logistico(
                                            v_modalidade_id, v_integration_id,
                                            v_data_venda, p_agora)
     WHERE id = p_pedido_id;

    UPDATE public.metodos_envio_observados
       SET status        = 'CLASSIFICADO',
           modalidade_id = v_modalidade_id
     WHERE module_id         = v_module_id
       AND valor_normalizado = lower(btrim(v_chave))
       AND status            = 'NOVO';

    RETURN v_modalidade_id;
END;
$$;

COMMENT ON FUNCTION public.classificar_pedido_modalidade(integer, timestamptz) IS
  'Tres alvos por prioridade: CHAVE (identificador estavel), ROTULO (nome do canal), CANONICA (pedidos.modalidade_logistica, ultimo recurso). Nao casar nada nunca apaga classificacao anterior.';
