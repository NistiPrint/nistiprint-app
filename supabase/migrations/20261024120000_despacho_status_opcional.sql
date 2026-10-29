-- A Torre usa Em Andamento por padrão e pode incluir Pronto para Envio quando
-- o operador solicita. A configuração é local à transação para que consultas
-- paralelas nunca compartilhem o filtro.
DO $migration_view$
DECLARE
    v_projection text := '';
    v_seen text[] := ARRAY[]::text[];
    v_expression text;
    v_type text;
    v_col record;
BEGIN
    FOR v_col IN
        SELECT a.attname::text AS name
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relname = 'vw_pedidos_pendentes_despacho'
           AND c.relkind = 'v' AND a.attnum > 0 AND NOT a.attisdropped
         ORDER BY a.attnum
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
             JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relname = 'pedidos'
               AND a.attname = v_col.name AND a.attnum > 0 AND NOT a.attisdropped
        ) THEN
            v_expression := format('p.%I', v_col.name);
        ELSE
            v_expression := CASE v_col.name
              WHEN 'modalidade_codigo' THEN 'COALESCE(m.codigo, ''NAO_CLASSIFICADA'')'
              WHEN 'modalidade_nome' THEN 'COALESCE(m.nome, ''Modalidade nao classificada'')'
              WHEN 'modalidade_tipo_prazo' THEN 'COALESCE(m.tipo_prazo, ''FIXO'')'
              WHEN 'modalidade_ordem' THEN 'COALESCE(m.ordem_exibicao, 0)::smallint'
              WHEN 'modalidade_entrega_rapida' THEN 'COALESCE(m.entrega_rapida, false)'
              WHEN 'marketplace_nome' THEN 'i.instance_name'
              ELSE NULL
            END;
            IF v_expression IS NULL THEN
                RAISE EXCEPTION 'Coluna % da view de despacho nao pode ser preservada', v_col.name;
            END IF;
            SELECT format_type(a.atttypid, a.atttypmod) INTO v_type
              FROM pg_attribute a
             WHERE a.attrelid = 'public.vw_pedidos_pendentes_despacho'::regclass
               AND a.attname = v_col.name AND a.attnum > 0 AND NOT a.attisdropped;
            IF v_type IS NOT NULL THEN
                v_expression := format('(%s)::%s', v_expression, v_type);
            END IF;
        END IF;
        v_projection := concat_ws(', ', NULLIF(v_projection, ''),
            format('%s AS %I', v_expression, v_col.name));
        v_seen := array_append(v_seen, v_col.name);
    END LOOP;

    FOR v_col IN
        SELECT * FROM (VALUES
          ('modalidade_codigo', 'COALESCE(m.codigo, ''NAO_CLASSIFICADA'')'),
          ('modalidade_nome', 'COALESCE(m.nome, ''Modalidade nao classificada'')'),
          ('modalidade_tipo_prazo', 'COALESCE(m.tipo_prazo, ''FIXO'')'),
          ('modalidade_ordem', 'COALESCE(m.ordem_exibicao, 0)::smallint'),
          ('modalidade_entrega_rapida', 'COALESCE(m.entrega_rapida, false)'),
          ('marketplace_nome', 'i.instance_name')
        ) AS aliases(name, expression)
    LOOP
        IF NOT (v_col.name = ANY(v_seen)) THEN
            v_projection := concat_ws(', ', NULLIF(v_projection, ''),
                format('%s AS %I', v_col.expression, v_col.name));
            v_seen := array_append(v_seen, v_col.name);
        END IF;
    END LOOP;

    FOR v_col IN
        SELECT a.attname::text AS name
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relname = 'pedidos'
           AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
         ORDER BY a.attnum
    LOOP
        IF NOT (v_col.name = ANY(v_seen)) THEN
            v_projection := concat_ws(', ', NULLIF(v_projection, ''), format('p.%I', v_col.name));
            v_seen := array_append(v_seen, v_col.name);
        END IF;
    END LOOP;

    EXECUTE format($view$
      CREATE OR REPLACE VIEW public.vw_pedidos_pendentes_despacho AS
      SELECT %s
        FROM public.pedidos p
        LEFT JOIN public.modalidades_logisticas m ON m.id = p.modalidade_logistica_id
        LEFT JOIN public.installed_integrations i ON i.id = p.marketplace_integration_id
       WHERE p.despachado_em IS NULL
         AND p.situacao_pedido_id IN (2, 4)
         AND (p.situacao_pedido_id = 2 OR
              COALESCE(current_setting('app.despacho_incluir_pronto', true) = 'true', false))
         AND COALESCE(m.entra_na_torre, NOT COALESCE(p.is_fulfillment, false))
         AND (p.marketplace_module_id IS DISTINCT FROM 'mercadolivre'
              OR p.situacao_pedido_id <> 4
              OR COALESCE(current_setting('app.despacho_incluir_pronto', true) = 'true', false))
    $view$, v_projection);
END;
$migration_view$;

COMMENT ON VIEW public.vw_pedidos_pendentes_despacho IS
  'Pedidos pendentes da Torre. O padrão inclui somente Em Andamento (2); a opção transacional app.despacho_incluir_pronto inclui também Pronto para Envio (4). Produzido (3) fica fora.';

-- Leituras com escolha explícita. As versões antigas continuam servindo os
-- consumidores sem o parâmetro e veem somente Em Andamento por padrão.
CREATE OR REPLACE FUNCTION public.despacho_arvore_contexto(p_data date, p_incluir_pronto boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO public, pg_temp AS $$
BEGIN
    PERFORM set_config('app.despacho_incluir_pronto', COALESCE(p_incluir_pronto, false)::text, true);
    IF COALESCE(p_incluir_pronto, false) THEN
        RETURN public.despacho_arvore_contexto_raw(p_data);
    END IF;
    RETURN public.despacho_arvore_contexto(p_data);
END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_lotes_timeline(p_data date, p_incluir_pronto boolean)
RETURNS TABLE (
    integration_id integer, marketplace_nome text, modalidade_id integer,
    modalidade_codigo text, modalidade_nome text, tipo_prazo text,
    entrega_rapida boolean, data_limite_dia date, bucket_prazo text,
    qtd_pedidos integer, proxima_saida_em timestamptz, saida_apos_prazo boolean
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO public, pg_temp AS $$
BEGIN
    PERFORM set_config('app.despacho_incluir_pronto', COALESCE(p_incluir_pronto, false)::text, true);
    RETURN QUERY SELECT * FROM public.despacho_lotes_timeline(p_data);
END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_contexto(
    p_integration_id integer, p_modalidade_ids integer[], p_horizonte text[],
    p_data date, p_incluir_pronto boolean
)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO public, pg_temp AS $$
BEGIN
    PERFORM set_config('app.despacho_incluir_pronto', COALESCE(p_incluir_pronto, false)::text, true);
    RETURN public.despacho_escopo_contexto(
        p_integration_id, p_modalidade_ids, p_horizonte, p_data
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_escopo_lote(
    p_integration_id integer, p_modalidade_ids integer[], p_horizonte text[],
    p_data date, p_incluir_pronto boolean
)
RETURNS SETOF integer LANGUAGE plpgsql SECURITY DEFINER SET search_path TO public, pg_temp AS $$
BEGIN
    PERFORM set_config('app.despacho_incluir_pronto', COALESCE(p_incluir_pronto, false)::text, true);
    RETURN QUERY SELECT * FROM public.despacho_escopo_lote(
        p_integration_id, p_modalidade_ids, p_horizonte, p_data
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.despacho_lancar_lote(
    p_integration_id integer, p_modalidade_ids integer[], p_horizonte text[],
    p_data date, p_nome text, p_user_id text, p_observacoes text,
    p_incluir_pronto boolean
)
RETURNS TABLE (
    out_demanda_id integer, out_demanda_codigo text, out_total_pedidos integer,
    out_total_itens numeric, out_complementar boolean
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path TO public, pg_temp AS $$
DECLARE
    v_ids integer[];
    v_result record;
BEGIN
    PERFORM set_config('app.despacho_incluir_pronto', COALESCE(p_incluir_pronto, false)::text, true);
    SELECT array_agg(id ORDER BY id) INTO v_ids
      FROM public.despacho_escopo_lote(
          p_integration_id, p_modalidade_ids, p_horizonte, p_data
      ) AS id;
    IF COALESCE(array_length(v_ids, 1), 0) = 0 THEN
        RAISE EXCEPTION 'Escopo vazio' USING ERRCODE = 'no_data_found';
    END IF;
    -- Revalida e bloqueia o status até o lançamento terminar; status 3 não
    -- pode entrar nem mesmo se mudar enquanto o operador confirma o lote.
    SELECT array_agg(validos.id ORDER BY validos.id) INTO v_ids
      FROM (
          SELECT p.id
            FROM public.pedidos p
           WHERE p.id = ANY(v_ids)
             AND p.despachado_em IS NULL
             AND (p.situacao_pedido_id = 2 OR
                  (COALESCE(p_incluir_pronto, false) AND p.situacao_pedido_id = 4))
           FOR UPDATE
      ) AS validos;
    IF COALESCE(array_length(v_ids, 1), 0) = 0 THEN
        RAISE EXCEPTION 'Escopo sem pedidos pendentes' USING ERRCODE = 'no_data_found';
    END IF;
    SELECT * INTO v_result FROM public.despacho_lancar_pedidos(
        v_ids, p_nome, p_user_id, p_observacoes,
        jsonb_build_object(
            'integration_id', p_integration_id,
            'modalidade_ids', p_modalidade_ids,
            'horizonte', p_horizonte,
            'data_operacional', p_data,
            'incluir_pronto', COALESCE(p_incluir_pronto, false)
        )
    );
    RETURN QUERY SELECT v_result.out_demanda_id, v_result.out_demanda_codigo,
        v_result.out_total_pedidos, v_result.out_total_itens,
        v_result.out_complementar;
END;
$$;

REVOKE ALL ON FUNCTION public.despacho_arvore_contexto(date, boolean),
    public.despacho_lotes_timeline(date, boolean),
    public.despacho_escopo_contexto(integer, integer[], text[], date, boolean),
    public.despacho_escopo_lote(integer, integer[], text[], date, boolean),
    public.despacho_lancar_lote(integer, integer[], text[], date, text, text, text, boolean)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.despacho_arvore_contexto(date, boolean),
    public.despacho_lotes_timeline(date, boolean),
    public.despacho_escopo_contexto(integer, integer[], text[], date, boolean)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.despacho_escopo_lote(integer, integer[], text[], date, boolean),
    public.despacho_lancar_lote(integer, integer[], text[], date, text, text, text, boolean)
    TO service_role, authenticated;

-- O snapshot antigo foi agregado com o conjunto 2/3/4. Ele é descartável e
-- precisa ser reconstruído sob a regra padrão antes da próxima leitura.
DELETE FROM public.despacho_contexto_read_model;

NOTIFY pgrst, 'reload schema';
