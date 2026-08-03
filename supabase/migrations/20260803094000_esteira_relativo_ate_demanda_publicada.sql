-- O Turbo sai da esteira quando vira demanda publicada, nao quando recebe
-- `despachado_em`.
-- Contrato: docs/specs/02-domains/despacho/spec.md
--
-- ## Por que o criterio mudou
--
-- `despachado_em` marca "saiu da torre", que nao e a mesma coisa que "o
-- atendimento viu e tratou". Um pedido pode entrar num rascunho de demanda —
-- alguem comecou a montar o lote e parou no meio — e nesse estado o Turbo
-- continua sendo responsabilidade de ninguem, com o relogio correndo.
--
-- O criterio agora e pertencer a uma demanda com status diferente de RASCUNHO
-- (e nao cancelada). RASCUNHO nao esta em `_STATUS_VALIDOS` do
-- `demanda/status.py` justamente porque e um estado anterior a publicacao.
--
-- ## Diferenca deliberada em relacao a torre
--
-- `despacho_arvore` continua usando `despachado_em`. Nao e inconsistencia: a
-- torre conta o que ainda precisa ser lancado, e lancar e o que carimba
-- `despachado_em`. A esteira responde outra pergunta — "alguem ja assumiu este
-- prazo?" — e para ela o rascunho nao conta como assumido.
--
-- `em_rascunho` sai na resposta para a faixa poder dizer "em rascunho, ainda
-- nao publicado" em vez de repetir "novo Turbo" para algo que alguem ja
-- comecou a tratar.

DROP FUNCTION IF EXISTS public.despacho_esteira_relativo();

CREATE FUNCTION public.despacho_esteira_relativo()
RETURNS TABLE (
    pedido_id             integer,
    numero_pedido         text,
    marketplace_nome      text,
    modalidade_id         integer,
    modalidade_nome       text,
    modalidade_cor        text,
    nivel_interrupcao     smallint,
    data_venda            timestamptz,
    compromisso_em        timestamptz,
    minutos_restantes     integer,
    atrasado              boolean,
    em_rascunho           boolean,
    demanda_rascunho      text
)
LANGUAGE sql
STABLE
AS $fn$
    SELECT
        p.id,
        p.numero_pedido::text,
        COALESCE(ii.instance_name, 'Origem nao resolvida')::text,
        m.id,
        m.nome::text,
        m.cor::text,
        m.nivel_interrupcao,
        (p.data_venda AT TIME ZONE 'America/Sao_Paulo'),
        p.compromisso_logistico_em,
        -- floor, nao round: 39,7 minutos restantes e "39", nunca "40".
        -- Arredondar para cima um prazo regressivo devolve tempo que nao existe.
        floor(EXTRACT(epoch FROM (p.compromisso_logistico_em - now())) / 60)::integer,
        (p.compromisso_logistico_em <= now()),
        (rascunho.demanda_id IS NOT NULL),
        rascunho.demanda_id::text
      FROM public.pedidos p
      JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
      LEFT JOIN public.installed_integrations ii ON ii.id = p.marketplace_integration_id
      LEFT JOIN LATERAL (
            SELECT d.demanda_id
              FROM public.demandas_pedidos dp
              JOIN public.demandas_producao d ON d.id = dp.demanda_id
             WHERE dp.pedido_id = p.id
               AND d.status = 'RASCUNHO'
             ORDER BY d.created_at DESC
             LIMIT 1
      ) rascunho ON true
     WHERE m.tipo_prazo = 'RELATIVO'
       AND p.situacao_pedido_id IN (2, 3, 4)
       AND NOT EXISTS (
             SELECT 1
               FROM public.demandas_pedidos dp
               JOIN public.demandas_producao d ON d.id = dp.demanda_id
              WHERE dp.pedido_id = p.id
                AND d.status NOT IN ('RASCUNHO', 'CANCELADO', 'Cancelado')
       )
     -- FIFO por prazo, nao por chegada: o pedido que vence primeiro sai
     -- primeiro, mesmo que tenha entrado depois.
     ORDER BY p.compromisso_logistico_em NULLS FIRST, p.id;
$fn$;

COMMENT ON FUNCTION public.despacho_esteira_relativo() IS
  'Fila FIFO de prazo relativo. O pedido sai da fila quando entra em demanda publicada, nao quando recebe despachado_em: rascunho ainda nao e trabalho entregue ao atendimento.';

GRANT EXECUTE ON FUNCTION public.despacho_esteira_relativo() TO anon, authenticated;
