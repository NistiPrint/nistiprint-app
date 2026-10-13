-- Claim atomico do primeiro push: a solicitacao fica duravel antes da chamada
-- externa, inclusive se o worker cair logo depois do claim.
ALTER TABLE public.conversas_chat_shopee
    ADD COLUMN IF NOT EXISTS primeiro_webhook_em timestamptz;

CREATE OR REPLACE FUNCTION public.solicitar_primeira_sincronizacao_chat_shopee(
    p_conversation_id bigint,
    p_integration_id bigint
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_claimed boolean := false;
BEGIN
    INSERT INTO public.conversas_chat_shopee (
        conversation_id, installed_integration_id, primeiro_webhook_em,
        sincronizacao_solicitada_em
    ) VALUES (p_conversation_id, p_integration_id, now(), now())
    ON CONFLICT (conversation_id) DO NOTHING
    RETURNING true INTO v_claimed;
    IF COALESCE(v_claimed, false) THEN
        RETURN true;
    END IF;

    UPDATE public.conversas_chat_shopee AS c
       SET primeiro_webhook_em = now(),
           sincronizacao_solicitada_em = now(),
           installed_integration_id = COALESCE(c.installed_integration_id, p_integration_id),
           updated_at = now()
     WHERE c.conversation_id = p_conversation_id
       AND c.primeiro_webhook_em IS NULL
       AND (c.installed_integration_id IS NULL OR c.installed_integration_id = p_integration_id)
    RETURNING true INTO v_claimed;
    RETURN COALESCE(v_claimed, false);
END;
$$;

REVOKE ALL ON FUNCTION public.solicitar_primeira_sincronizacao_chat_shopee(bigint, bigint)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.solicitar_primeira_sincronizacao_chat_shopee(bigint, bigint)
    TO service_role;
