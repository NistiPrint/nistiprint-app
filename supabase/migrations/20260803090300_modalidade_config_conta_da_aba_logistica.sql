-- Corte e coleta por conta vem da aba Logistica, nao de suposicao.
--
-- `regras_logisticas_integracao` ja guardava os horarios reais, cadastrados
-- pela operacao na tela de integracoes. O seed de `modalidades_logisticas`
-- inventou valores "provisorios" em paralelo, e os quatro estavam errados:
--
--   Shopee    Comum  seed 18:00/08:00+1   real 13:00/17:00
--   Shopee    Flex   seed 12:00/13:00     real 13:00/13:00
--   ML        Comum  seed 18:00/08:00+1   real 15:00/19:00  (ponto Tamara)
--   ML        Flex   seed 12:00/13:00     real 12:00/14:00
--
-- O erro nao foi ter chutado: foi ter chutado com o dado certo a duas tabelas
-- de distancia. `compromisso_logistico_em` e a ordenacao canonica de toda a
-- producao, entao um corte errado nao aparece como campo errado em tela — ele
-- aparece como a fila inteira na ordem errada.
--
-- `modalidade_config_conta` e a tabela desenhada para override por conta, e
-- `resolver_compromisso_logistico` ja a consulta antes do catalogo. Projetar a
-- aba Logistica nela mantem uma unica fonte de verdade operacional enquanto
-- `regras_logisticas_integracao` e `modalidades_logisticas` nao sao unificadas
-- de fato (ver spec, "Migration and transition").
--
-- O vocabulario diverge nas duas pontas: a aba usa 'STANDARD', o catalogo usa
-- 'COMUM'. A traducao explicita abaixo e exatamente a divida que este
-- comentario registra — e a razao de a unificacao ainda ser necessaria.

INSERT INTO public.modalidade_config_conta (
    modalidade_id, integration_id, corte_horario, coleta_horario,
    coleta_dia_offset, ponto_coleta_id, ativo
)
SELECT
    m.id,
    r.marketplace_integration_id,
    r.horario_corte,
    r.horario_coleta,
    -- Coleta antes do corte so faz sentido no dia seguinte.
    CASE WHEN r.horario_coleta >= r.horario_corte THEN 0 ELSE 1 END,
    r.ponto_coleta_id,
    r.ativo
  FROM public.regras_logisticas_integracao r
  JOIN public.installed_integrations ii
    ON ii.id = r.marketplace_integration_id
  JOIN public.modalidades_logisticas m
    ON m.module_id = ii.module_id
   AND m.codigo = CASE r.modalidade
                    WHEN 'STANDARD' THEN 'COMUM'
                    WHEN 'EXPRESS'  THEN 'FLEX'
                    ELSE r.modalidade
                  END
 WHERE r.ativo
   AND r.horario_corte IS NOT NULL
   AND NOT EXISTS (
       SELECT 1 FROM public.modalidade_config_conta c
        WHERE c.modalidade_id  = m.id
          AND c.integration_id = r.marketplace_integration_id
   );

-- Alinhar tambem o catalogo, para a conta que ainda nao tem override herdar um
-- default plausivel em vez do chute anterior.
UPDATE public.modalidades_logisticas m
   SET corte_horario     = c.corte_horario,
       coleta_horario    = c.coleta_horario,
       coleta_dia_offset = c.coleta_dia_offset,
       updated_at        = now()
  FROM public.modalidade_config_conta c
 WHERE c.modalidade_id = m.id
   AND m.tipo_prazo = 'FIXO';

-- Recalcular o compromisso de todo pedido pendente com os horarios corretos.
DO $do$
DECLARE r record; v integer := 0;
BEGIN
    FOR r IN SELECT id FROM public.pedidos
              WHERE despachado_em IS NULL AND situacao_pedido_id IN (2, 3, 4)
              ORDER BY id
    LOOP
        PERFORM public.classificar_pedido_modalidade(r.id);
        v := v + 1;
    END LOOP;
    RAISE NOTICE '[compromisso] % pedidos recalculados', v;
END;
$do$;
