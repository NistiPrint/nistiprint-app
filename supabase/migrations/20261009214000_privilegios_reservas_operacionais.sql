-- Operational reservations are an internal ledger read/written by the API
-- server with service_role. They must not be directly mutable through the
-- public Supabase API using anon or authenticated credentials.
ALTER TABLE public.estoque_reservas_operacionais ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.estoque_reservas_operacionais FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.estoque_reservas_operacionais TO service_role;

-- service_role bypasses RLS by design; this policy also makes the intended
-- access explicit if the role's bypass attribute is changed in a future setup.
CREATE POLICY estoque_reservas_operacionais_service_role_all
    ON public.estoque_reservas_operacionais
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);
