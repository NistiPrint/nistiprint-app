-- Colunas de modalidade, compromisso logistico e despacho em pedidos.
-- Contrato: docs/specs/02-domains/despacho/data-model.md
--
-- Tres decisoes materializadas aqui:
--
-- 1. Chave estavel separada de rotulo. metodo_envio_chave e a base da
--    classificacao (Shopee: logistics_channel_id); metodo_envio_rotulo e
--    exibicao e alerta (shipping_carrier). Renomear o rotulo na origem nao
--    pode reclassificar pedido nenhum.
--
-- 2. compromisso_logistico_em unifica FIXO e RELATIVO num unico instante, para
--    que torre de despacho, esteira, lista de demandas e painel de producao
--    compartilhem literalmente o mesmo ORDER BY. Sem isso cada tela
--    reimplementa a regra e as ordens divergem.
--
-- 3. despachado_em e o predicado do indice parcial da arvore de totalizadores.
--    Derivar "ainda nao despachado" de demandas_pedidos a cada consulta impede
--    indice parcial e degrada com volume.
--
-- modalidade_logistica_id NULL significa nao classificado. Nunca preencher com
-- uma modalidade default: o pedido cai no no "Modalidade nao classificada",
-- continua listavel e lancavel, e e exibido com prioridade maxima.

ALTER TABLE public.pedidos
    ADD COLUMN IF NOT EXISTS modalidade_logistica_id     integer
        REFERENCES public.modalidades_logisticas(id),
    ADD COLUMN IF NOT EXISTS modalidade_regra_id         integer
        REFERENCES public.regras_classificacao_modalidade(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS metodo_envio_chave          text,
    ADD COLUMN IF NOT EXISTS metodo_envio_rotulo         text,
    ADD COLUMN IF NOT EXISTS modalidade_classificada_em  timestamptz,
    ADD COLUMN IF NOT EXISTS compromisso_logistico_em    timestamptz,
    ADD COLUMN IF NOT EXISTS despachado_em               timestamptz;

COMMENT ON COLUMN public.pedidos.modalidade_logistica_id IS
  'NULL = nao classificado. Nunca receber default: prazo desconhecido e a hipotese mais perigosa, pode ser um Turbo com 40 minutos correndo.';
COMMENT ON COLUMN public.pedidos.modalidade_regra_id IS
  'Regra que classificou o pedido. Explicabilidade: sem isso, "por que esse pedido caiu em Comum" vira investigacao manual em platform_fields.';
COMMENT ON COLUMN public.pedidos.metodo_envio_chave IS
  'Identificador estavel do metodo de envio na origem (Shopee: logistics_channel_id). Base da classificacao e do agrupamento.';
COMMENT ON COLUMN public.pedidos.metodo_envio_rotulo IS
  'Rotulo de exibicao do metodo de envio (Shopee: shipping_carrier). Exibicao e alerta apenas, nunca classificacao.';
COMMENT ON COLUMN public.pedidos.compromisso_logistico_em IS
  'Instante do compromisso com a origem. FIXO: data operacional + corte. RELATIVO: data_venda + offset_etiqueta_min. Nao classificado: data_venda (ordena no topo). Ordenacao canonica unica do sistema.';
COMMENT ON COLUMN public.pedidos.despachado_em IS
  'Preenchido na publicacao da demanda, na mesma transacao. Predicado dos indices parciais da arvore.';

-- --------------------------------------------------------------------------
-- demandas_producao: rastreabilidade do escopo que gerou o lote
-- --------------------------------------------------------------------------

ALTER TABLE public.demandas_producao
    ADD COLUMN IF NOT EXISTS modalidade_id      integer
        REFERENCES public.modalidades_logisticas(id),
    ADD COLUMN IF NOT EXISTS escopo_despacho    jsonb,
    ADD COLUMN IF NOT EXISTS demanda_origem_id  integer
        REFERENCES public.demandas_producao(id);

COMMENT ON COLUMN public.demandas_producao.escopo_despacho IS
  'Escopo reproduzivel do lancamento: {integration_id, modalidade_id, horizonte[], data_operacional, total_pedidos_no_lancamento, total_conferido_pelo_operador}.';
COMMENT ON COLUMN public.demandas_producao.demanda_origem_id IS
  'Liga o lote complementar de retardatarios a demanda original do mesmo escopo. A demanda em producao nunca e alterada por pedido que chega depois.';
COMMENT ON COLUMN public.demandas_producao.modalidade_logistica IS
  'DEPRECATED: espelho de modalidade_id durante a transicao. Nao usar como criterio de agrupamento em codigo novo.';

-- --------------------------------------------------------------------------
-- Indices: so cobrem o backlog aberto, nao o historico
-- --------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_pedidos_arvore_despacho
    ON public.pedidos (marketplace_integration_id, modalidade_logistica_id, data_limite_envio)
    WHERE despachado_em IS NULL;

CREATE INDEX IF NOT EXISTS ix_pedidos_compromisso
    ON public.pedidos (compromisso_logistico_em)
    WHERE despachado_em IS NULL;

CREATE INDEX IF NOT EXISTS ix_pedidos_modalidade_nao_classificada
    ON public.pedidos (marketplace_integration_id, metodo_envio_chave)
    WHERE modalidade_logistica_id IS NULL AND despachado_em IS NULL;

CREATE INDEX IF NOT EXISTS ix_pedidos_metodo_envio_chave
    ON public.pedidos (metodo_envio_chave)
    WHERE metodo_envio_chave IS NOT NULL;
