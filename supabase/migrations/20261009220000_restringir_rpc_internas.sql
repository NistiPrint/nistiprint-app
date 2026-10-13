-- These SECURITY DEFINER routines are internal trigger helpers or are called
-- only by the trusted API/worker. Public and authenticated clients must not
-- invoke them directly through PostgREST.
REVOKE ALL ON FUNCTION public.atualizar_chave_combinacao_variacao()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.auditar_cadastro_produto()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.logistica_janelas_efetivas(bigint, date)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.recalcular_completude_conversa(bigint, integer, boolean, boolean, text)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.registrar_alteracao_sku()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.registrar_conversa_chat_shopee()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restore_mercadolivre_personalizations_from_log(integer, text, bigint, text, jsonb)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.atualizar_chave_combinacao_variacao() TO service_role;
GRANT EXECUTE ON FUNCTION public.auditar_cadastro_produto() TO service_role;
GRANT EXECUTE ON FUNCTION public.logistica_janelas_efetivas(bigint, date) TO service_role;
GRANT EXECUTE ON FUNCTION public.recalcular_completude_conversa(bigint, integer, boolean, boolean, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.registrar_alteracao_sku() TO service_role;
GRANT EXECUTE ON FUNCTION public.registrar_conversa_chat_shopee() TO service_role;
GRANT EXECUTE ON FUNCTION public.restore_mercadolivre_personalizations_from_log(integer, text, bigint, text, jsonb) TO service_role;
