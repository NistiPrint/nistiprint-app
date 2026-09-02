-- Funções SECURITY DEFINER são usadas apenas por triggers, nunca como RPC pública.
REVOKE ALL ON FUNCTION public.registrar_alteracao_sku() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.auditar_cadastro_produto() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_alteracao_sku() TO service_role;
GRANT EXECUTE ON FUNCTION public.auditar_cadastro_produto() TO service_role;