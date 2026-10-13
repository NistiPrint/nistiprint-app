-- All access to these operational/configuration tables flows through the
-- Flask API or worker, which use service_role and enforce domain permissions.
-- Browser sessions must not be able to bypass those checks via PostgREST.
DO $migration$
DECLARE
    v_table text;
    v_policy record;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'canal_modalidade_mapeamento',
        'consolidacoes_pedido',
        'demandas_overrides',
        'integration_mapping_rules',
        'janelas_despacho_execucoes',
        'pedidos_nao_classificados',
        'perfis_fiscais',
        'produto_alias_conflitos',
        'produto_anuncios',
        'produto_eixo_opcao_componentes',
        'produto_eixo_opcoes',
        'produto_eixos',
        'produto_pai_eixos',
        'produto_precos',
        'produto_sku_historico',
        'produto_tags',
        'produto_variacao_valores',
        'regras_consolidacao_canal'
    ]
    LOOP
        IF to_regclass(format('public.%I', v_table)) IS NULL THEN
            RAISE EXCEPTION 'Tabela operacional pública ausente: %', v_table;
        END IF;

        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', v_table);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated', v_table);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO service_role', v_table);

        FOR v_policy IN
            SELECT policyname
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = v_table
              AND 'authenticated' = ANY(roles)
              AND cmd IN ('INSERT', 'UPDATE', 'DELETE', 'ALL')
              AND (coalesce(qual, '') = 'true' OR coalesce(with_check, '') = 'true')
        LOOP
            EXECUTE format('DROP POLICY %I ON public.%I', v_policy.policyname, v_table);
        END LOOP;

        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
            v_table || '_service_role_all', v_table
        );
    END LOOP;
END;
$migration$;
