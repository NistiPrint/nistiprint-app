-- The cold report builds several bounded aggregates before populating its
-- 60-second cache. Allow that first request to finish under PostgREST.
ALTER FUNCTION public.gestao_report_cached(date, date, jsonb, boolean)
  SET statement_timeout = '30s';
