-- Janela de coleta de prazo relativo (Turbo).
-- Contrato: docs/specs/02-domains/despacho/spec.md, "Modalidades de prazo relativo"
--
-- ## O buraco
--
-- `modalidades_logisticas` ja sabia expressar prazo relativo desde o seed
-- (`tipo_prazo = 'RELATIVO'`, `offset_etiqueta_min`, `offset_coleta_min`), mas
-- `regras_logisticas_integracao` — a unica tabela com tela — so tinha
-- `horario_corte` e `horario_coleta`, ambos NOT NULL. Nao havia como cadastrar
-- Turbo por conta: o formato da tabela negava o formato da modalidade.
--
-- ## Por que a forma muda, e nao so os valores
--
-- Prazo relativo nao e "prazo fixo com outro horario". Sao dois modelos de
-- tempo distintos:
--
--   FIXO      hora de parede, compartilhada por todo o lote do dia.
--             "Corte 13:00" e a mesma instrucao para 140 pedidos.
--   RELATIVO  relogio proprio por pedido, ancorado na venda.
--             "40 minutos" e uma instrucao diferente para cada pedido.
--
-- Por isso o trigger zera os campos da outra forma em vez de deixa-los
-- conviver. Uma linha Turbo com `horario_corte = '13:00'` esquecido de uma
-- edicao anterior mentiria para quem le a tabela, e `resolver_compromisso_logistico`
-- escolheria o ramo errado se algum dia passasse a olhar o campo em vez do
-- `tipo_prazo`.
--
-- Mesma razao para forcar `dias_semana` = todos: uma esteira FIFO nao tem dia
-- de atendimento. O Turbo que cai no sabado tem o mesmo relogio do que cai na
-- terca — o prazo e do cliente, nao da agenda do galpao.

ALTER TABLE public.regras_logisticas_integracao
    ADD COLUMN IF NOT EXISTS offset_etiqueta_min integer,
    ADD COLUMN IF NOT EXISTS offset_coleta_min   integer;

ALTER TABLE public.regras_logisticas_integracao
    ALTER COLUMN horario_corte  DROP NOT NULL,
    ALTER COLUMN horario_coleta DROP NOT NULL,
    ALTER COLUMN horario_limite DROP NOT NULL;

ALTER TABLE public.regras_logisticas_integracao
    DROP CONSTRAINT IF EXISTS regras_logisticas_integracao_forma_ck;

-- Uma das duas formas, nunca nenhuma. O NOT NULL saiu para permitir RELATIVO,
-- e este CHECK impede que a saida do NOT NULL vire uma linha vazia.
ALTER TABLE public.regras_logisticas_integracao
    ADD CONSTRAINT regras_logisticas_integracao_forma_ck
    CHECK (
        (horario_corte IS NOT NULL AND horario_coleta IS NOT NULL)
     OR (offset_etiqueta_min IS NOT NULL AND offset_coleta_min IS NOT NULL)
    );

COMMENT ON COLUMN public.regras_logisticas_integracao.offset_etiqueta_min IS
  'Prazo de etiqueta em minutos apos a venda, para modalidade RELATIVO. E o "corte" dessa modalidade.';
COMMENT ON COLUMN public.regras_logisticas_integracao.offset_coleta_min IS
  'Prazo de coleta em minutos apos a venda, para modalidade RELATIVO.';

CREATE OR REPLACE FUNCTION public.tg_regra_logistica_sync_modalidade()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_codigo varchar(50);
    v_tipo   varchar(20);
BEGIN
    IF NEW.modalidade_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT codigo, tipo_prazo INTO v_codigo, v_tipo
      FROM public.modalidades_logisticas WHERE id = NEW.modalidade_id;

    NEW.modalidade := CASE v_codigo WHEN 'COMUM' THEN 'STANDARD' ELSE v_codigo END;

    IF v_tipo = 'RELATIVO' THEN
        IF NEW.offset_etiqueta_min IS NULL OR NEW.offset_coleta_min IS NULL THEN
            RAISE EXCEPTION 'Modalidade % e de prazo RELATIVO: informe offset de etiqueta e de coleta em minutos', v_codigo
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        NEW.horario_corte  := NULL;
        NEW.horario_coleta := NULL;
        NEW.horario_limite := NULL;
        NEW.coleta_dia_offset := 0;
        NEW.dias_semana := ARRAY[1, 2, 3, 4, 5, 6, 7];
    ELSE
        IF NEW.horario_corte IS NULL OR NEW.horario_coleta IS NULL THEN
            RAISE EXCEPTION 'Modalidade % e de prazo FIXO: informe hora de corte e de coleta', v_codigo
                USING ERRCODE = 'invalid_parameter_value';
        END IF;
        NEW.offset_etiqueta_min := NULL;
        NEW.offset_coleta_min   := NULL;
        NEW.horario_limite := COALESCE(NEW.horario_limite, NEW.horario_coleta);
        NEW.coleta_dia_offset := CASE WHEN NEW.horario_coleta >= NEW.horario_corte THEN 0 ELSE 1 END;
    END IF;

    RETURN NEW;
END;
$fn$;

-- --------------------------------------------------------------------------
-- Offset por conta vence o do catalogo, como o horario de corte ja vencia.
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.resolver_compromisso_logistico(
    p_modalidade_id  integer,
    p_integration_id integer,
    p_data_venda     timestamptz,
    p_agora          timestamptz DEFAULT now()
)
RETURNS timestamptz
LANGUAGE plpgsql
STABLE
AS $fn$
DECLARE
    c_tz     constant text := 'America/Sao_Paulo';
    v_tipo   text;
    v_offset integer;
    v_corte  time;
    v_base   date;
    v_result timestamptz;
BEGIN
    IF p_modalidade_id IS NULL THEN
        RETURN COALESCE(p_data_venda, p_agora);
    END IF;

    SELECT ml.tipo_prazo,
           COALESCE(r.offset_etiqueta_min, ml.offset_etiqueta_min),
           COALESCE(r.horario_corte, ml.corte_horario)
      INTO v_tipo, v_offset, v_corte
      FROM public.modalidades_logisticas ml
      LEFT JOIN public.regras_logisticas_integracao r
             ON r.modalidade_id = ml.id
            AND r.marketplace_integration_id = p_integration_id
            AND r.ativo
     WHERE ml.id = p_modalidade_id
     ORDER BY r.prioridade_uso DESC NULLS LAST, r.id
     LIMIT 1;

    IF v_tipo IS NULL THEN
        RETURN COALESCE(p_data_venda, p_agora);
    END IF;

    IF v_tipo = 'RELATIVO' THEN
        -- Ancorado na venda, nunca em now(): o relogio do Turbo comeca quando o
        -- cliente comprou. Reprocessar o pedido amanha nao pode empurrar o
        -- prazo dele para amanha.
        RETURN COALESCE(p_data_venda, p_agora) + make_interval(mins => COALESCE(v_offset, 0));
    END IF;

    v_base   := (p_agora AT TIME ZONE c_tz)::date;
    v_result := ((v_base + v_corte) AT TIME ZONE c_tz);

    IF v_result <= p_agora THEN
        v_result := ((v_base + 1 + v_corte) AT TIME ZONE c_tz);
    END IF;

    RETURN v_result;
END;
$fn$;

-- Turbo da conta Shopee: etiqueta +40min, coleta +60min apos a venda.
INSERT INTO public.regras_logisticas_integracao (
    marketplace_integration_id, modalidade_id, modalidade, tipo_envio,
    offset_etiqueta_min, offset_coleta_min, prioridade_uso, ativo, descricao
)
SELECT ii.id, m.id, 'TURBO', 'COLETA_LOCAL', 40, 60, 100, true,
       'Shopee Turbo: etiqueta 40min e coleta 60min apos a venda'
  FROM public.installed_integrations ii
  JOIN public.modalidades_logisticas m
    ON m.module_id = ii.module_id AND m.codigo = 'TURBO'
 WHERE ii.module_id = 'shopee'
   AND NOT EXISTS (
       SELECT 1 FROM public.regras_logisticas_integracao r
        WHERE r.marketplace_integration_id = ii.id AND r.modalidade_id = m.id
   );
