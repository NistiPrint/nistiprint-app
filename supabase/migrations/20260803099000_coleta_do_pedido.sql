-- O corte e regra de PERTENCIMENTO, nao prazo de producao.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## O erro que isto corrige
--
-- O card dizia "pronto ate 13:00" usando o horario de corte. Errado nos dois
-- sentidos:
--
--   1. O corte nao e prazo de producao. Ele diz QUAIS pedidos entram na coleta:
--      "todos os pedidos feitos ate as 13h precisam ser produzidos e enviados
--      ate as 17h". Quem chega 13h05 nao esta atrasado — esta no proximo lote.
--   2. O prazo de producao e a COLETA (17h), nao o corte.
--
-- A consequencia pratica era pior que o rotulo errado: com o corte tratado como
-- "proxima janela a partir de agora", as 13h04 todos os pedidos da Shopee Comum
-- eram jogados para a coleta de amanha — inclusive os 168 pagos antes das 13h,
-- que precisavam sair hoje as 17h. A urgencia do lote do dia desaparecia da
-- tela no minuto em que ela mais importa.
--
-- ## Duas saidas para o mesmo lote
--
-- Um corte pode ter mais de uma janela de despacho: coleta local as 17h e
-- entrega em ponto de coleta as 19h. Sao duas chances para o MESMO lote, nao
-- dois lotes. Isso e o que permite registrar coleta parcial as 17h sem a
-- demanda ficar atrasada — ainda ha caminhao as 19h.
--
-- Cadastro: duas linhas em `regras_logisticas_integracao` com o mesmo
-- `horario_corte` e `tipo_envio` diferente. O unique index
-- (integracao, modalidade, tipo_envio) ja permitia isso.

CREATE OR REPLACE FUNCTION public.janelas_logisticas(
    p_modalidade_id  integer,
    p_integration_id integer,
    p_dia            date
)
RETURNS TABLE (
    tipo_envio      text,
    coleta_em       timestamptz,
    ponto_coleta_id integer,
    ponto_nome      text
)
LANGUAGE sql
STABLE
AS $fn$
    SELECT r.tipo_envio::text,
           ((p_dia + COALESCE(r.coleta_dia_offset, 0)
                   + COALESCE(r.horario_coleta, r.horario_corte)) AT TIME ZONE 'America/Sao_Paulo'),
           r.ponto_coleta_id,
           pc.nome::text
      FROM public.regras_logisticas_integracao r
      LEFT JOIN public.pontos_coleta pc ON pc.id = r.ponto_coleta_id
     WHERE r.ativo
       AND r.modalidade_id = p_modalidade_id
       AND r.marketplace_integration_id = p_integration_id
       AND r.horario_corte IS NOT NULL
       AND EXTRACT(isodow FROM p_dia)::integer = ANY (COALESCE(r.dias_semana, ARRAY[1,2,3,4,5,6,7]))
     ORDER BY 2;
$fn$;

COMMENT ON FUNCTION public.janelas_logisticas(integer, integer, date) IS
  'Saidas de despacho de um lote num dia. Um mesmo corte pode ter mais de uma: coleta local as 17h e entrega em ponto de coleta as 19h sao duas chances para o mesmo lote.';

-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.coleta_do_pedido(
    p_modalidade_id  integer,
    p_integration_id integer,
    p_referencia     timestamptz,
    p_agora          timestamptz DEFAULT now()
)
RETURNS TABLE (
    corte_em       timestamptz,
    coleta_em      timestamptz,
    prazo_final_em timestamptz
)
LANGUAGE plpgsql
STABLE
AS $fn$
DECLARE
    c_tz    constant text := 'America/Sao_Paulo';
    v_tipo  text;
    v_corte time;
    v_dias  integer[];
    v_ref   timestamptz;
    v_dia   date;
    v_corte_dt timestamptz;
    v_primeira timestamptz;
    v_ultima   timestamptz;
    d       integer;
BEGIN
    IF p_modalidade_id IS NULL OR p_integration_id IS NULL THEN
        RETURN;
    END IF;

    SELECT ml.tipo_prazo INTO v_tipo
      FROM public.modalidades_logisticas ml WHERE ml.id = p_modalidade_id;

    -- RELATIVO nao tem coleta recorrente: cada pedido tem o proprio relogio.
    IF v_tipo IS DISTINCT FROM 'FIXO' THEN
        RETURN;
    END IF;

    -- Corte do lote e o mais cedo entre as regras da conta. Duas saidas
    -- compartilham o mesmo corte: e um lote so, com duas chances de sair.
    SELECT min(r.horario_corte),
           (SELECT array_agg(DISTINCT dia)
              FROM public.regras_logisticas_integracao r2,
                   LATERAL unnest(COALESCE(r2.dias_semana, ARRAY[1,2,3,4,5,6,7])) AS dia
             WHERE r2.ativo AND r2.modalidade_id = p_modalidade_id
               AND r2.marketplace_integration_id = p_integration_id)
      INTO v_corte, v_dias
      FROM public.regras_logisticas_integracao r
     WHERE r.ativo AND r.modalidade_id = p_modalidade_id
       AND r.marketplace_integration_id = p_integration_id
       AND r.horario_corte IS NOT NULL;

    IF v_corte IS NULL THEN
        RETURN;
    END IF;

    v_ref := COALESCE(p_referencia, p_agora);

    -- Comeca no dia do pedido, nao no dia de hoje: o lote e definido por quando
    -- o pedido foi feito.
    FOR d IN 0..21 LOOP
        v_dia := (LEAST(v_ref, p_agora) AT TIME ZONE c_tz)::date + d;

        IF NOT (EXTRACT(isodow FROM v_dia)::integer = ANY (v_dias)) THEN
            CONTINUE;
        END IF;

        v_corte_dt := ((v_dia + v_corte) AT TIME ZONE c_tz);

        -- Corte anterior ao pedido nao podia inclui-lo.
        IF v_corte_dt < v_ref THEN
            CONTINUE;
        END IF;

        SELECT min(j.coleta_em), max(j.coleta_em)
          INTO v_primeira, v_ultima
          FROM public.janelas_logisticas(p_modalidade_id, p_integration_id, v_dia) j;

        IF v_primeira IS NULL THEN
            CONTINUE;
        END IF;

        -- Lote cuja ultima saida ja passou nao recebe mais nada: o pedido que
        -- ficou para tras entra no proximo. Ele continua atrasado perante o
        -- marketplace — isso os buckets de prazo mostram — mas o caminhao dele
        -- agora e outro.
        IF v_ultima <= p_agora THEN
            CONTINUE;
        END IF;

        corte_em       := v_corte_dt;
        coleta_em      := v_primeira;
        prazo_final_em := v_ultima;
        RETURN NEXT;
        RETURN;
    END LOOP;
END;
$fn$;

COMMENT ON FUNCTION public.coleta_do_pedido(integer, integer, timestamptz, timestamptz) IS
  'Coleta a que um pedido pertence. O corte nao e prazo de producao: e a regra de pertencimento. Pedido feito ate o corte sai naquela coleta; feito depois, na proxima. Prazo de producao e a coleta — ou a ultima saida, quando o lote tem mais de uma.';

GRANT EXECUTE ON FUNCTION public.janelas_logisticas(integer, integer, date) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.coleta_do_pedido(integer, integer, timestamptz, timestamptz) TO anon, authenticated;
