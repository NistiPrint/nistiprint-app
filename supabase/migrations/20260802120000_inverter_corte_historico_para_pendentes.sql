-- Inverte o alvo do corte historico: atualizar despacho, nao situacao final.
--
-- A versao anterior (20260802110000) escolheu como alvo os pedidos ja
-- finalizados (Enviado/Entregue/Cancelado/Devolvido) sem despachado_em, e os
-- carimbava como Entregue. Isso sobrescrevia Cancelado e Devolvido — situacoes
-- comerciais finais e corretas — com um status errado.
--
-- Decisao revista: Cancelado, Entregue e Devolvido sao situacoes finais e nao
-- devem ser tocadas. Quem precisa do corte e o pedido que ainda aparece como
-- pendente (Em Aberto, Em Andamento/Producao, Produzido, Pronto para Envio,
-- Enviado) com data_venda antiga: isso e, com certeza, falta de atualizacao de
-- status (o pedido seguiu o fluxo real e nunca voltou pra atualizar o banco),
-- nao trabalho pendente de verdade.
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
    -- Em Aberto, Em Andamento, Produzido, Pronto para Envio, Enviado.
    -- Pedido cuja situacao nunca avancou no banco, apesar do tempo passado.
    c_pendentes   constant integer[] := ARRAY[1, 2, 3, 4, 5];
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
       AND p.situacao_pedido_id = ANY (c_pendentes)
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
  'Corte historico: marca como Entregue e carimba despachado_em nos pedidos ainda pendentes (Em Aberto/Em Andamento/Produzido/Pronto para Envio/Enviado) com data_venda ate p_data — situacao presa por falta de atualizacao. Nao toca Cancelado/Entregue/Devolvido (situacoes finais) nem situacao nula. p_dry_run=true devolve a previa sem alterar. Desfazer: manutencao_desfazer_lote(lote).';
