-- Manutencao: marcar pedidos antigos como entregues e tira-los da torre.
--
-- Contexto: `pedidos.despachado_em` nasceu na migration 20260802100001 e so foi
-- backfillado para pedidos ligados a demandas publicadas. Todo pedido que nunca
-- passou por demanda ficou com despachado_em nulo e por isso aparece na torre de
-- despacho como backlog aberto — inclusive os ja enviados, entregues, cancelados
-- e devolvidos. Resultado observado: 6.215 pedidos Shopee "em aberto" dos quais
-- so ~770 eram trabalho pendente real.
--
-- Esta ferramenta e um corte historico pontual, nao rotina.
--
-- ATENCAO — operacao destrutiva por decisao explicita do usuario:
-- pedidos Cancelados e Devolvidos dentro do periodo tambem passam a Entregue.
-- Isso sobrescreve status comercial real. Por isso:
--   1. `p_dry_run = true` devolve a previa sem alterar nada;
--   2. o estado anterior de cada pedido vai para `manutencao_status_log`,
--      o que torna a operacao reversivel.
--
-- Pedidos ainda pendentes (Em Aberto, Em Andamento, Produzido, Pronto para
-- Envio) NAO sao tocados: podem ser trabalho que ainda precisa ser produzido.
-- Situacao nula tambem nao e tocada — sem saber o estado, o seguro e nao mexer.

-- --------------------------------------------------------------------------
-- 1. Log de reversibilidade
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.manutencao_status_log (
    id                     bigserial PRIMARY KEY,
    operacao               varchar(60) NOT NULL,
    lote                   uuid NOT NULL,
    pedido_id              integer NOT NULL,
    situacao_anterior_id   integer,
    situacao_nova_id       integer,
    despachado_em_anterior timestamptz,
    executado_em           timestamptz NOT NULL DEFAULT now(),
    executado_por          text
);

CREATE INDEX IF NOT EXISTS ix_manutencao_status_log_lote
    ON public.manutencao_status_log (lote);

COMMENT ON TABLE public.manutencao_status_log IS
  'Estado anterior de pedidos alterados por ferramentas de manutencao em massa. Existe para que um corte historico possa ser desfeito: sem isso, sobrescrever Cancelado/Devolvido como Entregue seria irreversivel.';

ALTER TABLE public.manutencao_status_log ENABLE ROW LEVEL SECURITY;

-- --------------------------------------------------------------------------
-- 2. Aplicacao (com dry-run)
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.manutencao_marcar_entregues_ate(
    p_data          date,
    p_dry_run       boolean DEFAULT true,
    p_executado_por text DEFAULT 'System'
)
RETURNS TABLE (
    out_lote               uuid,
    out_situacao_anterior  text,
    out_qtd                integer
)
LANGUAGE plpgsql
AS $$
DECLARE
    -- Enviado, Entregue, Cancelado, Devolvido. Ciclo comercial encerrado.
    c_finalizados constant integer[] := ARRAY[5, 6, 7, 8];
    c_entregue    constant integer   := 6;
    v_lote        uuid := gen_random_uuid();
BEGIN
    IF p_data IS NULL THEN
        RAISE EXCEPTION 'Data de corte e obrigatoria' USING ERRCODE = 'invalid_parameter_value';
    END IF;

    CREATE TEMP TABLE tmp_alvo ON COMMIT DROP AS
    SELECT p.id AS pedido_id,
           p.situacao_pedido_id,
           p.despachado_em
      FROM public.pedidos p
     WHERE p.despachado_em IS NULL
       AND p.situacao_pedido_id = ANY (c_finalizados)
       -- data_venda e timestamp: comparar por dia para "ate xx/xx/xxxx"
       -- incluir o dia inteiro da data informada.
       AND p.data_venda < (p_data + 1)::timestamp;

    IF NOT p_dry_run THEN
        INSERT INTO public.manutencao_status_log (
            operacao, lote, pedido_id, situacao_anterior_id,
            situacao_nova_id, despachado_em_anterior, executado_por
        )
        SELECT 'marcar_entregues_ate', v_lote, a.pedido_id, a.situacao_pedido_id,
               c_entregue, a.despachado_em, p_executado_por
          FROM tmp_alvo a;

        UPDATE public.pedidos p
           SET situacao_pedido_id = c_entregue,
               despachado_em      = now(),
               updated_at         = now()
          FROM tmp_alvo a
         WHERE p.id = a.pedido_id;
    END IF;

    RETURN QUERY
    SELECT v_lote,
           COALESCE(sp.nome, 'Sem situacao')::text,
           count(*)::integer
      FROM tmp_alvo a
      LEFT JOIN public.situacoes_pedido sp ON sp.id = a.situacao_pedido_id
     GROUP BY sp.nome
     ORDER BY count(*) DESC;
END;
$$;

COMMENT ON FUNCTION public.manutencao_marcar_entregues_ate(date, boolean, text) IS
  'Corte historico: marca como Entregue e carimba despachado_em nos pedidos ja finalizados (Enviado/Entregue/Cancelado/Devolvido) com data_venda ate p_data. Nao toca pedidos pendentes nem situacao nula. p_dry_run=true devolve a previa sem alterar. Desfazer: manutencao_desfazer_lote(lote).';

-- --------------------------------------------------------------------------
-- 3. Desfazer um lote
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.manutencao_desfazer_lote(p_lote uuid)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_total integer;
BEGIN
    UPDATE public.pedidos p
       SET situacao_pedido_id = l.situacao_anterior_id,
           despachado_em      = l.despachado_em_anterior,
           updated_at         = now()
      FROM public.manutencao_status_log l
     WHERE l.lote = p_lote
       AND p.id = l.pedido_id;

    GET DIAGNOSTICS v_total = ROW_COUNT;

    DELETE FROM public.manutencao_status_log WHERE lote = p_lote;

    RETURN v_total;
END;
$$;

COMMENT ON FUNCTION public.manutencao_desfazer_lote(uuid) IS
  'Restaura situacao_pedido_id e despachado_em ao estado anterior ao lote e limpa o log. E o que torna o corte historico uma decisao reversivel.';
