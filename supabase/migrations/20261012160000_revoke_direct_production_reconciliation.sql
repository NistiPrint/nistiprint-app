-- Keep the balance-writing reconciliation function private to the
-- SECURITY DEFINER lease-confirmation wrapper. Application workers must not
-- invoke this legacy helper directly without operation and lease validation.
REVOKE ALL ON FUNCTION public.reconciliar_item_estoque(
    integer, integer, jsonb, jsonb, uuid, character varying
) FROM PUBLIC, anon, authenticated, service_role;

-- The wrapper remains the only application entry point for production
-- reconciliation and is still callable by the backend service role.
GRANT EXECUTE ON FUNCTION public.confirmar_reconciliacao_producao(
    uuid, text, integer, integer, jsonb, jsonb, uuid, text, text, uuid, uuid[]
) TO service_role;
