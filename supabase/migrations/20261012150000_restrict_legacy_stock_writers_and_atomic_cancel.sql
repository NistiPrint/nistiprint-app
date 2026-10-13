-- Route collection-cancellation compensation through the idempotent stock
-- command and remove client/legacy access to direct stock writers.

CREATE OR REPLACE FUNCTION public.despacho_cancelar_demanda(
    p_demanda_id integer,
    p_motivo text DEFAULT NULL::text,
    p_user_id text DEFAULT 'System'::text
)
RETURNS TABLE(out_demanda_codigo text, out_pedidos_devolvidos integer, out_estornos_estoque integer)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_status text;
    v_codigo text;
    v_scope jsonb;
    v_operation_id uuid;
    v_source jsonb;
    v_movimentos jsonb;
    v_semantica jsonb;
    v_content_hash text;
    v_resultado jsonb;
    v_user_id integer;
    v_pedidos integer := 0;
    v_estornos integer := 0;
    v_agora timestamptz := now();
BEGIN
    v_operation_id := extensions.uuid_generate_v5(
        'a2bd88f7-2b3e-47c6-bc09-4dc594c4e236'::uuid,
        'cancelamento-coleta:' || p_demanda_id::text
    );

    SELECT d.status, d.demanda_id, COALESCE(d.escopo_despacho, '{}'::jsonb)
      INTO v_status, v_codigo, v_scope
      FROM public.demandas_producao d
     WHERE d.id = p_demanda_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Demanda % nao encontrada', p_demanda_id USING ERRCODE = 'no_data_found';
    END IF;

    SELECT count(*) INTO v_pedidos
      FROM public.demandas_pedidos WHERE demanda_id = p_demanda_id;

    -- A repetição após timeout devolve o resultado anterior, sem gerar outra
    -- compensação nem rejeitar uma operação que já foi confirmada.
    IF v_status IN ('CANCELADO', 'Cancelado') THEN
        v_estornos := COALESCE(
            (v_scope->>'estornos_estoque')::integer,
            (SELECT count(*)::integer
               FROM public.movimentacoes_estoque m
               JOIN public.itens_demanda i ON i.id = m.item_demanda_id
              WHERE i.demanda_id = p_demanda_id
                AND m.estagio = 'estorno_coleta')
        );
        RETURN QUERY SELECT v_codigo, v_pedidos, v_estornos;
        RETURN;
    END IF;

    v_user_id := CASE WHEN p_user_id ~ '^-?[0-9]+$' THEN p_user_id::integer ELSE NULL END;
    v_source := jsonb_build_object(
        'source_type', 'DEMANDA_CANCELAMENTO',
        'source_id', p_demanda_id::text,
        'demanda_id', p_demanda_id
    );

    -- Vincula cada compensação ao movimento de saída original. Isso permite
    -- estornar várias coletas parciais do mesmo item sem uma compensação
    -- esconder as demais.
    SELECT COALESCE(jsonb_agg(
        jsonb_build_object(
            'produto_id', m.produto_id,
            'deposito_id', m.deposito_id,
            'tipo_movimentacao', 'ESTORNO',
            'quantidade', abs(m.quantidade),
            'motivo', format('Estorno da coleta: demanda cancelada (mov. origem %s). %s',
                             m.id, COALESCE(p_motivo, '')),
            'documento_referencia', m.id::text,
            'origem_tipo', NULL,
            'item_demanda_id', m.item_demanda_id,
            'estagio', 'estorno_coleta',
            'correlation_id', v_operation_id
        ) ORDER BY m.produto_id, m.deposito_id, m.id
    ), '[]'::jsonb)
      INTO v_movimentos
      FROM public.movimentacoes_estoque m
      JOIN public.itens_demanda i ON i.id = m.item_demanda_id
     WHERE i.demanda_id = p_demanda_id
       AND m.tipo_movimentacao = 'SAIDA_COLETA'
       AND NOT EXISTS (
           SELECT 1 FROM public.movimentacoes_estoque e
            WHERE e.estagio = 'estorno_coleta'
              AND e.documento_referencia = m.id::text
       );

    IF jsonb_array_length(v_movimentos) > 0 THEN
        v_semantica := jsonb_build_object(
            'command_type', 'CANCELAMENTO_COLETA',
            'source', v_source,
            'actor_id', v_user_id,
            'movimentos', v_movimentos
        );
        v_content_hash := encode(
            extensions.digest(convert_to(v_semantica::text, 'UTF8'), 'sha256'),
            'hex'
        );
        v_resultado := public.executar_comando_estoque(
            v_operation_id,
            'CANCELAMENTO_COLETA',
            v_content_hash,
            v_source,
            v_user_id,
            v_movimentos
        );
        v_estornos := jsonb_array_length(COALESCE(v_resultado->'movimentos', '[]'::jsonb));

        INSERT INTO public.demanda_estoque_processado (
            item_id, demanda_id, estagio, quantidade, correlation_id,
            saldo_acumulado, produto_id, tipo_movimentacao, created_at
        )
        SELECT estorno.item_demanda_id,
               p_demanda_id,
               'estorno_coleta',
               estorno.quantidade,
               v_operation_id::text,
               estorno.saldo_depois,
               estorno.produto_id,
               'ESTORNO',
               v_agora
          FROM public.movimentacoes_estoque estorno
         WHERE estorno.operation_id = v_operation_id
           AND estorno.estagio = 'estorno_coleta'
        ON CONFLICT DO NOTHING;
    END IF;

    UPDATE public.demandas_producao
       SET status = 'CANCELADO',
           updated_at = v_agora,
           escopo_despacho = COALESCE(escopo_despacho, '{}'::jsonb) || jsonb_build_object(
               'cancelado_em', v_agora,
               'cancelado_por', p_user_id,
               'cancelamento_motivo', COALESCE(p_motivo, 'Nao informado'),
               'estorno_correlation_id', v_operation_id,
               'estorno_operation_id', v_operation_id,
               'estornos_estoque', v_estornos,
               'pedidos_devolvidos', v_pedidos
           )
     WHERE id = p_demanda_id;

    INSERT INTO public.eventos_auditoria (tipo_evento, descricao, registro_id, dados_novos, created_at)
    VALUES (
        'DEMANDA_CANCELADA_COM_DEVOLUCAO',
        'Demanda cancelada; pedidos devolvidos a torre de despacho.',
        p_demanda_id,
        jsonb_build_object(
            'demanda_id', p_demanda_id,
            'demanda_codigo', v_codigo,
            'status_anterior', v_status,
            'pedidos_devolvidos', v_pedidos,
            'estornos_estoque', v_estornos,
            'motivo', p_motivo,
            'usuario', p_user_id,
            'operation_id', v_operation_id
        ),
        v_agora
    );

    RETURN QUERY SELECT v_codigo, v_pedidos, v_estornos;
END;
$function$;

-- These service methods remain in use, but direct Supabase clients do not call
-- them. Backend access is preserved through service_role only.
REVOKE ALL ON FUNCTION public.despacho_cancelar_demanda(integer, text, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_cancelar_demanda(integer, text, text)
    TO service_role;
REVOKE ALL ON FUNCTION public.despacho_excluir_demanda(integer, text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_excluir_demanda(integer, text)
    TO service_role;
REVOKE ALL ON FUNCTION public.get_alertas_producao()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_alertas_producao() TO service_role;

-- Effective BOM and diagnostic/allocation lookups are backend-only.
REVOKE ALL ON FUNCTION public.bom_efetiva_produto(integer)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bom_efetiva_produto(integer) TO service_role;
REVOKE ALL ON FUNCTION public.bom_efetiva_produtos(integer[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bom_efetiva_produtos(integer[]) TO service_role;
REVOKE ALL ON FUNCTION public.calcular_saldo_a_processar(character varying, character varying, numeric)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.calcular_saldo_a_processar(character varying, character varying, numeric)
    TO service_role;
REVOKE ALL ON FUNCTION public.simular_reconciliacao_item(integer, numeric)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.simular_reconciliacao_item(integer, numeric) TO service_role;
REVOKE ALL ON FUNCTION public.snapshot_estoque_item(integer)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.snapshot_estoque_item(integer) TO service_role;
REVOKE ALL ON FUNCTION public.verificar_alocacao_existente(character varying)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.verificar_alocacao_existente(character varying) TO service_role;
REVOKE ALL ON FUNCTION public.verificar_alocacao_existente(text)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.verificar_alocacao_existente(text) TO service_role;

-- Retired non-idempotent writers have no repository callers. Preserve their
-- definitions for historical compatibility, but make every direct call fail.
REVOKE ALL ON FUNCTION public.cancelar_alocacao(character varying, text)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.marcar_alocacao_processada(character varying)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.registrar_movimentacao_primaria(
    integer, integer, character varying, numeric, text, integer, integer, character varying, uuid
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.registrar_saida_coleta_demanda(integer, text)
    FROM PUBLIC, anon, authenticated, service_role;

-- The application writes these aggregates through authenticated API/service
-- code and transactional RPCs. Browser Realtime may still use SELECT grants.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE
    public.estoque_atual,
    public.movimentacoes_estoque,
    public.demanda_alocacoes_estoque,
    public.demanda_estoque_processado,
    public.eventos_producao_v2,
    public.itens_demanda,
    public.demandas_producao,
    public.ordens_producao,
    public.componentes_ordem_producao
FROM PUBLIC, anon, authenticated;
