-- Proximo corte e proxima coleta, calculados na leitura.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## O bug
--
-- A torre exibia "proximo compromisso 03/08, 12:00" no dia 04/08. Nao era erro
-- de calculo: 274 dos 342 pedidos pendentes tinham
-- `compromisso_logistico_em` no passado.
--
-- `compromisso_logistico_em` e gravado uma vez, quando o pedido e classificado.
-- Para modalidade FIXO isso e uma janela **diaria recorrente** — "corte 13:00"
-- nao e um instante, e uma regra que se repete. Guardar a proxima ocorrencia
-- como timestamp cria um valor que envelhece sozinho toda meia-noite. O campo
-- estava certo no instante em que foi escrito e errado em todos os seguintes.
--
-- Um campo que precisa estar sempre no futuro nao pode ser um snapshot.
--
-- ## Para RELATIVO continua armazenado, e esta certo
--
-- Turbo ancora em `pedidos.data_venda` + offset: e um instante de verdade, um
-- por pedido, e pode estar no passado — atraso de Turbo e informacao real, e
-- exatamente o que a esteira precisa mostrar. Por isso esta funcao devolve
-- vazio para RELATIVO em vez de inventar uma janela.
--
-- ## dias_semana
--
-- Mercado Livre atende Seg-Sex. Consultada num sabado, a funcao devolve a
-- segunda — nao o proprio sabado com hora futura. Ignorar isso faria a torre
-- prometer uma coleta que ninguem vem buscar.

CREATE OR REPLACE FUNCTION public.proxima_janela_logistica(
    p_modalidade_id  integer,
    p_integration_id integer,
    p_agora          timestamptz DEFAULT now()
)
RETURNS TABLE (corte_em timestamptz, coleta_em timestamptz)
LANGUAGE plpgsql
STABLE
AS $fn$
DECLARE
    c_tz     constant text := 'America/Sao_Paulo';
    v_tipo   text;
    v_corte  time;
    v_coleta time;
    v_offset smallint;
    v_dias   integer[];
    v_dia    date;
    v_corte_dt  timestamptz;
    d        integer;
BEGIN
    IF p_modalidade_id IS NULL THEN
        RETURN;
    END IF;

    SELECT ml.tipo_prazo,
           COALESCE(r.horario_corte,     ml.corte_horario),
           COALESCE(r.horario_coleta,    ml.coleta_horario),
           COALESCE(r.coleta_dia_offset, ml.coleta_dia_offset, 0),
           COALESCE(r.dias_semana,       ARRAY[1,2,3,4,5,6,7])
      INTO v_tipo, v_corte, v_coleta, v_offset, v_dias
      FROM public.modalidades_logisticas ml
      LEFT JOIN public.regras_logisticas_integracao r
             ON r.modalidade_id = ml.id
            AND r.marketplace_integration_id = p_integration_id
            AND r.ativo
     WHERE ml.id = p_modalidade_id
     ORDER BY r.prioridade_uso DESC NULLS LAST, r.id
     LIMIT 1;

    IF v_tipo IS DISTINCT FROM 'FIXO' OR v_corte IS NULL THEN
        RETURN;
    END IF;

    -- 14 dias cobrem qualquer combinacao de dias_semana, inclusive uma
    -- modalidade que so atenda um dia por semana.
    FOR d IN 0..14 LOOP
        v_dia := (p_agora AT TIME ZONE c_tz)::date + d;

        IF NOT (EXTRACT(isodow FROM v_dia)::integer = ANY (v_dias)) THEN
            CONTINUE;
        END IF;

        v_corte_dt := ((v_dia + v_corte) AT TIME ZONE c_tz);

        -- Corte que ja passou nao aceita mais pedido: aquele lote fechou.
        IF v_corte_dt <= p_agora THEN
            CONTINUE;
        END IF;

        corte_em  := v_corte_dt;
        coleta_em := ((v_dia + v_offset + COALESCE(v_coleta, v_corte)) AT TIME ZONE c_tz);
        RETURN NEXT;
        RETURN;
    END LOOP;
END;
$fn$;

COMMENT ON FUNCTION public.proxima_janela_logistica(integer, integer, timestamptz) IS
  'Proximo corte e proxima coleta de uma modalidade FIXO nesta conta, sempre no futuro e respeitando dias_semana. Calculado na leitura: uma janela diaria recorrente nao pode ser guardada como timestamp.';

GRANT EXECUTE ON FUNCTION public.proxima_janela_logistica(integer, integer, timestamptz) TO anon, authenticated;
