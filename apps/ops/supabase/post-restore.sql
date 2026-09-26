-- Execute depois da restauração dos dumps e confirme pg_cron antes.
-- Seguro para reexecução: remove apenas jobs com este nome e agenda o alvo atual.
DO $$
DECLARE
  existing_job_id bigint;
BEGIN
  FOR existing_job_id IN
    SELECT jobid FROM cron.job WHERE jobname = 'purga-retencao-logs'
  LOOP
    PERFORM cron.unschedule(existing_job_id);
  END LOOP;

  PERFORM cron.schedule(
    'purga-retencao-logs',
    '17 * * * *',
    'SELECT public.purgar_logs_retencao(20000)'
  );
END
$$;

-- Restaure os canais necessários se não vierem no dump do projeto Cloud.
DO $$
DECLARE
  missing_tables text[];
BEGIN
  SELECT array_agg(required.table_name)
  INTO missing_tables
  FROM unnest(ARRAY['demandas_producao', 'itens_demanda']) AS required(table_name)
  WHERE NOT EXISTS (
    SELECT 1
    FROM pg_publication_tables p
    WHERE p.pubname = 'supabase_realtime'
      AND p.schemaname = 'public'
      AND p.tablename = required.table_name
  );

  IF missing_tables IS NOT NULL THEN
    EXECUTE format(
      'ALTER PUBLICATION supabase_realtime ADD TABLE %s',
      (SELECT string_agg(format('public.%I', table_name), ', ')
       FROM unnest(missing_tables) AS missing(table_name))
    );
  END IF;
END
$$;
