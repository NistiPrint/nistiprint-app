-- Logistic rules are read/written through the authenticated API server. The
-- previous authenticated policies allowed every signed-in user to modify or
-- delete every rule, bypassing the API's administrator checks.
ALTER TABLE public.regras_logisticas_integracao ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS authenticated_delete_regras_logisticas_integracao
    ON public.regras_logisticas_integracao;
DROP POLICY IF EXISTS authenticated_insert_regras_logisticas_integracao
    ON public.regras_logisticas_integracao;
DROP POLICY IF EXISTS authenticated_select_regras_logisticas_integracao
    ON public.regras_logisticas_integracao;
DROP POLICY IF EXISTS authenticated_update_regras_logisticas_integracao
    ON public.regras_logisticas_integracao;

REVOKE ALL ON TABLE public.regras_logisticas_integracao FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.regras_logisticas_integracao TO service_role;

CREATE POLICY regras_logisticas_integracao_service_role_all
    ON public.regras_logisticas_integracao
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);
