-- Unificacao: `regras_logisticas_integracao` passa a apontar para o catalogo.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## O problema
--
-- Existiam tres vocabularios para a mesma coisa:
--
--   logistics_canonicalization.py     STANDARD FLEX FULFILLMENT RETIRADA
--   regras_logisticas_integracao      STANDARD FLEX (varchar livre)
--   modalidades_logisticas            COMUM FLEX TURBO FULL RETIRADA
--
-- Mais duas tabelas descrevendo a mesma janela de coleta:
-- `regras_logisticas_integracao` (rica, com tela e seis consumidores) e
-- `modalidade_config_conta` (pobre, sem tela, um consumidor).
--
-- ## A direcao
--
-- A spec dizia "regras_logisticas_canal e absorvida por modalidades_logisticas".
-- Na pratica a absorcao correta e a inversa: quem tem tela, historico e
-- consumidores e a tabela de regras. Ela nao vira dado do catalogo — ela ganha
-- uma FK para ele. `modalidade_config_conta` some, porque era a mesma tabela
-- escrita de novo com menos campos.
--
-- A coluna `modalidade` (texto) sobrevive como projecao mantida por trigger.
-- Isso e o que permite unificar sem reescrever no mesmo commit
-- `logistica_coleta_service`, `consolidation_service`, `demanda/core`,
-- `production_lot_suggestions_service` e `demandas_sugestoes_service`, que a
-- leem por nome. A projecao e a ponte; a FK e a verdade.

ALTER TABLE public.regras_logisticas_integracao
    ADD COLUMN IF NOT EXISTS modalidade_id integer
        REFERENCES public.modalidades_logisticas(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS coleta_dia_offset smallint NOT NULL DEFAULT 0;

UPDATE public.regras_logisticas_integracao r
   SET modalidade_id = m.id,
       coleta_dia_offset = CASE WHEN r.horario_coleta >= r.horario_corte THEN 0 ELSE 1 END
  FROM public.installed_integrations ii, public.modalidades_logisticas m
 WHERE ii.id = r.marketplace_integration_id
   AND m.module_id = ii.module_id
   AND m.codigo = CASE r.modalidade
                    WHEN 'STANDARD' THEN 'COMUM'
                    WHEN 'EXPRESS'  THEN 'FLEX'
                    ELSE r.modalidade
                  END
   AND r.modalidade_id IS NULL;

-- Uma janela por (conta, modalidade, tipo de envio). Duas janelas para a mesma
-- modalidade e conta com o mesmo tipo de envio sao a mesma regra escrita duas
-- vezes, e `prioridade_uso` so mascara o conflito.
CREATE UNIQUE INDEX IF NOT EXISTS uq_regra_logistica_conta_modalidade
    ON public.regras_logisticas_integracao (marketplace_integration_id, modalidade_id, tipo_envio)
 WHERE ativo AND modalidade_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.tg_regra_logistica_sync_modalidade()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_codigo varchar(50);
BEGIN
    IF NEW.modalidade_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT codigo INTO v_codigo
      FROM public.modalidades_logisticas WHERE id = NEW.modalidade_id;

    -- 'COMUM' -> 'STANDARD' na saida: o vocabulario legado sobrevive so aqui.
    NEW.modalidade := CASE v_codigo WHEN 'COMUM' THEN 'STANDARD' ELSE v_codigo END;

    IF NEW.horario_coleta IS NOT NULL AND NEW.horario_corte IS NOT NULL THEN
        NEW.coleta_dia_offset := CASE WHEN NEW.horario_coleta >= NEW.horario_corte THEN 0 ELSE 1 END;
    END IF;

    RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS tg_regra_logistica_sync_modalidade ON public.regras_logisticas_integracao;
CREATE TRIGGER tg_regra_logistica_sync_modalidade
    BEFORE INSERT OR UPDATE ON public.regras_logisticas_integracao
    FOR EACH ROW EXECUTE FUNCTION public.tg_regra_logistica_sync_modalidade();

-- --------------------------------------------------------------------------
-- O compromisso logistico passa a ler a aba Logistica
-- --------------------------------------------------------------------------
-- `compromisso_logistico_em` e a ordenacao canonica de toda a producao. Ele
-- estava sendo calculado a partir de um catalogo que ninguem edita, enquanto
-- os horarios reais estavam na tela que a operacao usa todo dia.

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

    SELECT ml.tipo_prazo, ml.offset_etiqueta_min,
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

COMMENT ON FUNCTION public.resolver_compromisso_logistico(integer, integer, timestamptz, timestamptz) IS
  'Corte por conta vem de regras_logisticas_integracao (aba Logistica); o catalogo e so o default de quem nao tem janela cadastrada.';

-- Duplicata resolvida. O ponto de coleta e por conta, nunca por catalogo:
-- a mesma modalidade tem pontos diferentes em contas diferentes.
DROP TABLE IF EXISTS public.modalidade_config_conta;

ALTER TABLE public.modalidades_logisticas
    DROP COLUMN IF EXISTS ponto_coleta_id;

COMMENT ON COLUMN public.regras_logisticas_integracao.modalidade_id IS
  'Fonte de verdade da modalidade. A coluna `modalidade` (texto) e projecao mantida por trigger, apenas para os consumidores legados.';
