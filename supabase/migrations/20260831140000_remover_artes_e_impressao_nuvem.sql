-- Os objetos do Storage devem ser removidos pela Storage API antes desta migration.
-- Verifique o script de limpeza correspondente antes de aplicar em produção.
DROP TABLE IF EXISTS public.print_jobs;
DROP TABLE IF EXISTS public.product_artworks;