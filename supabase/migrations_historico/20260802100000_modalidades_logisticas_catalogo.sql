-- Catalogo de modalidades logisticas.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--           docs/specs/02-domains/despacho/data-model.md
--
-- Substitui o par (pedidos.is_flex boolean, demandas_producao.modalidade_logistica
-- varchar) por um cadastro editavel. Motivacao concreta: a Shopee lancou
-- "Entrega Turbo" (canais 90011/90012), cuja regra e etiqueta em 40min e coleta
-- em 60min a partir do pedido. Um booleano nao comporta uma terceira modalidade
-- e um enum em COMMENT nao comporta uma regra de prazo.
--
-- Convencao de escopo, identica a integration_status_mappings:
--   module_id      = plataforma ('shopee', 'mercadolivre', ...)
--   integration_id = conta instalada; NULL significa "vale para toda conta da
--                    plataforma". Linha com conta preenchida tem precedencia.
--
-- Nao toca em pedidos nem em demandas_producao. Pode ir a producao isolada.

-- --------------------------------------------------------------------------
-- 1. Modalidades: a regra publicada pela plataforma
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.modalidades_logisticas (
    id                   serial PRIMARY KEY,
    module_id            varchar(100) NOT NULL,
    codigo               varchar(50)  NOT NULL,
    nome                 varchar(100) NOT NULL,
    tipo_prazo           varchar(20)  NOT NULL
                         CHECK (tipo_prazo IN ('FIXO', 'RELATIVO')),
    politica_lote        varchar(20)  NOT NULL DEFAULT 'LOTE'
                         CHECK (politica_lote IN ('LOTE', 'INDIVIDUAL')),
    nivel_interrupcao    smallint     NOT NULL DEFAULT 0,
    corte_horario        time,
    coleta_horario       time,
    coleta_dia_offset    smallint     NOT NULL DEFAULT 0,
    ponto_coleta_id      integer      REFERENCES public.pontos_coleta(id),
    offset_etiqueta_min  integer,
    offset_coleta_min    integer,
    cor                  varchar(7),
    ordem_exibicao       smallint     NOT NULL DEFAULT 100,
    ativo                boolean      NOT NULL DEFAULT true,
    created_at           timestamptz  NOT NULL DEFAULT now(),
    updated_at           timestamptz  NOT NULL DEFAULT now(),

    CONSTRAINT modalidades_logisticas_module_codigo_key
        UNIQUE (module_id, codigo),
    CONSTRAINT modalidades_logisticas_prazo_fixo_ck
        CHECK (tipo_prazo <> 'FIXO' OR corte_horario IS NOT NULL),
    CONSTRAINT modalidades_logisticas_prazo_relativo_ck
        CHECK (tipo_prazo <> 'RELATIVO' OR offset_etiqueta_min IS NOT NULL)
);

COMMENT ON TABLE public.modalidades_logisticas IS
  'Regra de despacho publicada pelo marketplace (Comum, Flex, Turbo, Full). Cadastro editavel: adicionar modalidade nao pode exigir deploy.';
COMMENT ON COLUMN public.modalidades_logisticas.tipo_prazo IS
  'FIXO: deadline e um horario do dia, acumula em lote diario. RELATIVO: deadline e data_venda + offset, cada pedido tem relogio proprio.';
COMMENT ON COLUMN public.modalidades_logisticas.coleta_dia_offset IS
  'Dias somados a data operacional para a coleta. Cobre corte 18:00 com coleta no dia seguinte 08:00.';
COMMENT ON COLUMN public.modalidades_logisticas.offset_etiqueta_min IS
  'Somente tipo_prazo RELATIVO. Minutos apos data_venda para emissao da etiqueta. Shopee Turbo = 40.';
COMMENT ON COLUMN public.modalidades_logisticas.nivel_interrupcao IS
  '0 nao interrompe a fila de producao corrente. Valores maiores furam a fila sem exigir decisao do operador.';
COMMENT ON COLUMN public.modalidades_logisticas.politica_lote IS
  'INDIVIDUAL significa que uma demanda de 1 pedido e o resultado esperado, nao uma anomalia.';

-- --------------------------------------------------------------------------
-- 2. Config por conta: o que varia por loja e regiao
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.modalidade_config_conta (
    id                 serial PRIMARY KEY,
    modalidade_id      integer NOT NULL
                       REFERENCES public.modalidades_logisticas(id) ON DELETE CASCADE,
    integration_id     integer NOT NULL
                       REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
    corte_horario      time,
    coleta_horario     time,
    coleta_dia_offset  smallint,
    ponto_coleta_id    integer REFERENCES public.pontos_coleta(id),
    ativo              boolean NOT NULL DEFAULT true,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT modalidade_config_conta_key UNIQUE (modalidade_id, integration_id)
);

COMMENT ON TABLE public.modalidade_config_conta IS
  'Sobrescrita por conta instalada. Ausencia de linha significa "usa o default da plataforma", nao "desativado". Resolucao: COALESCE(config.campo, modalidade.campo).';

-- --------------------------------------------------------------------------
-- 3. Regras de classificacao
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.regras_classificacao_modalidade (
    id              serial PRIMARY KEY,
    module_id       varchar(100) NOT NULL,
    integration_id  integer REFERENCES public.installed_integrations(id) ON DELETE CASCADE,
    modalidade_id   integer NOT NULL
                    REFERENCES public.modalidades_logisticas(id) ON DELETE CASCADE,
    campo_origem    varchar(120) NOT NULL,
    alvo            varchar(10) NOT NULL DEFAULT 'CHAVE'
                    CHECK (alvo IN ('CHAVE', 'ROTULO')),
    operador        varchar(20) NOT NULL DEFAULT 'IGUAL'
                    CHECK (operador IN ('IGUAL', 'CONTEM', 'PREFIXO', 'REGEX')),
    valor           text NOT NULL,
    case_sensitive  boolean NOT NULL DEFAULT false,
    prioridade      smallint NOT NULL DEFAULT 100,
    ativo           boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_regras_class_modalidade_lookup
  ON public.regras_classificacao_modalidade (module_id, prioridade, id)
  WHERE ativo;

COMMENT ON TABLE public.regras_classificacao_modalidade IS
  'Mapeia valor observado no payload da origem para modalidade. N regras para 1 modalidade e o caso normal: Shopee Turbo tem dois canais logisticos (90011 e 90012) com a mesma regra operacional.';
COMMENT ON COLUMN public.regras_classificacao_modalidade.campo_origem IS
  'Caminho logico em pedido_snapshots.platform_fields, documental. Preferir identificador estavel (logistics_channel_id) a rotulo de exibicao (shipping_carrier).';
COMMENT ON COLUMN public.regras_classificacao_modalidade.alvo IS
  'Contra qual coluna de pedidos a regra casa: CHAVE (metodo_envio_chave) ou ROTULO (metodo_envio_rotulo).';
COMMENT ON COLUMN public.regras_classificacao_modalidade.prioridade IS
  'Menor avalia primeiro. Regras por ID estavel usam prioridade baixa; fallback por rotulo usa prioridade alta e e defensivo, nunca principal.';

-- --------------------------------------------------------------------------
-- 4. Metodos de envio observados: deteccao de modalidade nova
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.metodos_envio_observados (
    id                      serial PRIMARY KEY,
    module_id               varchar(100) NOT NULL,
    integration_id          integer REFERENCES public.installed_integrations(id) ON DELETE SET NULL,
    campo_origem            varchar(120) NOT NULL,
    valor_bruto             text NOT NULL,
    valor_normalizado       text NOT NULL,
    rotulo_bruto            text,
    status                  varchar(20) NOT NULL DEFAULT 'NOVO'
                            CHECK (status IN ('NOVO', 'CLASSIFICADO', 'IGNORADO')),
    modalidade_id           integer REFERENCES public.modalidades_logisticas(id) ON DELETE SET NULL,
    ocorrencias             integer NOT NULL DEFAULT 1,
    primeira_ocorrencia_em  timestamptz NOT NULL DEFAULT now(),
    ultima_ocorrencia_em    timestamptz NOT NULL DEFAULT now(),
    pedido_exemplo_id       integer,
    alerta_emitido_em       timestamptz,

    CONSTRAINT metodos_envio_observados_key
        UNIQUE (module_id, campo_origem, valor_normalizado)
);

CREATE INDEX IF NOT EXISTS ix_metodos_envio_observados_novos
  ON public.metodos_envio_observados (module_id, ultima_ocorrencia_em DESC)
  WHERE status = 'NOVO';

COMMENT ON TABLE public.metodos_envio_observados IS
  'Todo valor distinto de metodo de envio visto no ingest. Valor nunca visto gera alerta de administracao em vez de virar STANDARD por omissao. E o gatilho de manutencao quando o marketplace lanca uma modalidade nova.';
COMMENT ON COLUMN public.metodos_envio_observados.valor_bruto IS
  'Chave estavel (ex.: logistics_channel_id 90011).';
COMMENT ON COLUMN public.metodos_envio_observados.rotulo_bruto IS
  'Texto de exibicao (ex.: "Entrega Turbo (SPF)"). O alerta precisa dos dois: so a chave nao permite reconhecer o que e, so o rotulo nao permite escrever regra estavel.';

-- --------------------------------------------------------------------------
-- 5. updated_at
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.tg_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tg_modalidades_logisticas_touch ON public.modalidades_logisticas;
CREATE TRIGGER tg_modalidades_logisticas_touch
    BEFORE UPDATE ON public.modalidades_logisticas
    FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

DROP TRIGGER IF EXISTS tg_modalidade_config_conta_touch ON public.modalidade_config_conta;
CREATE TRIGGER tg_modalidade_config_conta_touch
    BEFORE UPDATE ON public.modalidade_config_conta
    FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();

DROP TRIGGER IF EXISTS tg_regras_class_modalidade_touch ON public.regras_classificacao_modalidade;
CREATE TRIGGER tg_regras_class_modalidade_touch
    BEFORE UPDATE ON public.regras_classificacao_modalidade
    FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
