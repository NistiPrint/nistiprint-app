-- These tables are used by server-side API/worker routines and are not
-- browser-facing data contracts. Restrict direct PostgREST access to the
-- service role while preserving owner/SECURITY DEFINER and backend access.
DO $migration$
DECLARE
    v_table text;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'ficha_tecnica_classificacao_pendente',
        'ingest_daily_stats',
        'produto_variacao_backfill_revisao',
        'regra_logistica_modalidades',
        'task_daily_stats',
        'webhook_daily_stats'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', v_table);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated', v_table);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO service_role', v_table);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
            v_table || '_service_role_all', v_table
        );
    END LOOP;
END;
$migration$;
