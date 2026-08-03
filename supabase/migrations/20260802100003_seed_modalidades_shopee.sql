-- Seed das modalidades Shopee e das regras de classificacao do Turbo.
-- Contrato: docs/specs/02-domains/despacho/data-model.md
--
-- Fonte do Turbo: get_order_detail da Shopee expoe
--   logistics_channel_id  90011 (Entrega Turbo) e 90012 (Entrega Turbo SPF)
--   shipping_carrier      "Entrega Turbo" e "Entrega Turbo (SPF)"
-- Regra operacional confirmada: etiqueta em ate 40 minutos apos o pedido,
-- coleta 1 hora apos o pedido. Os dois canais compartilham a mesma regra, entao
-- sao uma modalidade com duas regras de classificacao, nao duas modalidades.
--
-- Regras de COMUM e FLEX sao deliberadamente omitidas. Nao sabemos os
-- logistics_channel_id reais desses canais, e inventar regra por rotulo criaria
-- classificacao fragil justamente no maior volume. Sem regra, esses pedidos caem
-- no no "Modalidade nao classificada", metodos_envio_observados registra os IDs
-- reais vindos do trafego de producao e a administracao cadastra as regras com
-- os valores corretos. O mecanismo de deteccao existe para isso.

-- --------------------------------------------------------------------------
-- 1. Modalidades
-- --------------------------------------------------------------------------

INSERT INTO public.modalidades_logisticas (
    module_id, codigo, nome, tipo_prazo, politica_lote, nivel_interrupcao,
    corte_horario, coleta_horario, coleta_dia_offset,
    offset_etiqueta_min, offset_coleta_min, cor, ordem_exibicao
) VALUES
    -- ATENCAO: corte e coleta de COMUM e FLEX abaixo sao provisorios, extraidos
    -- da rotina descrita pela operacao. Confirmar por conta em
    -- modalidade_config_conta antes de confiar no compromisso calculado.
    ('shopee', 'COMUM', 'Comum', 'FIXO', 'LOTE', 0,
     '18:00', '08:00', 1, NULL, NULL, '#5F5E5A', 30),

    ('shopee', 'FLEX', 'Flex', 'FIXO', 'LOTE', 0,
     '12:00', '13:00', 0, NULL, NULL, '#BA7517', 20),

    ('shopee', 'TURBO', 'Turbo', 'RELATIVO', 'INDIVIDUAL', 10,
     NULL, NULL, 0, 40, 60, '#D85A30', 10)
ON CONFLICT (module_id, codigo) DO NOTHING;

-- --------------------------------------------------------------------------
-- 2. Regras de classificacao do Turbo
-- --------------------------------------------------------------------------

-- Principais: identificador estavel. Renomeacao do rotulo pela Shopee nao
-- reclassifica nenhum pedido.
INSERT INTO public.regras_classificacao_modalidade (
    module_id, modalidade_id, campo_origem, alvo, operador, valor, prioridade
)
SELECT 'shopee', m.id, 'logistics_channel_id', 'CHAVE', 'IGUAL', v.valor, 10
  FROM public.modalidades_logisticas m
 CROSS JOIN (VALUES ('90011'), ('90012')) AS v(valor)
 WHERE m.module_id = 'shopee'
   AND m.codigo = 'TURBO'
   AND NOT EXISTS (
       SELECT 1 FROM public.regras_classificacao_modalidade r
        WHERE r.module_id = 'shopee'
          AND r.modalidade_id = m.id
          AND r.alvo = 'CHAVE'
          AND r.valor = v.valor
   );

-- Defensiva: se a Shopee lancar um canal Turbo com ID novo antes de alguem
-- cadastrar, o pedido cai em Turbo em vez de ficar sem prazo. O alerta do ID
-- desconhecido continua sendo emitido para a regra estavel ser criada depois.
-- Prioridade alta = avaliada por ultimo. Nunca deve ser a regra principal.
INSERT INTO public.regras_classificacao_modalidade (
    module_id, modalidade_id, campo_origem, alvo, operador, valor, prioridade
)
SELECT 'shopee', m.id, 'shipping_carrier', 'ROTULO', 'CONTEM', 'Entrega Turbo', 900
  FROM public.modalidades_logisticas m
 WHERE m.module_id = 'shopee'
   AND m.codigo = 'TURBO'
   AND NOT EXISTS (
       SELECT 1 FROM public.regras_classificacao_modalidade r
        WHERE r.module_id = 'shopee'
          AND r.modalidade_id = m.id
          AND r.alvo = 'ROTULO'
          AND r.valor = 'Entrega Turbo'
   );
