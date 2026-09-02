CREATE OR REPLACE VIEW public.view_mensagens_chat_ai_v2
WITH (security_invoker = true) AS
SELECT m.id, m.installed_integration_id, m.from_id, m.to_id,
       m.from_user_name, m.to_user_name, m.conversation_id,
       m.created_at, m.type, m.content, m.source_content,
       v.display_content
FROM public.mensagem_chat_shopee m
JOIN public.view_mensagens_chat_ai v ON v.id = m.id;
REVOKE ALL ON TABLE public.view_mensagens_chat_ai_v2 FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.view_mensagens_chat_ai_v2 TO service_role;
CREATE INDEX IF NOT EXISTS idx_mensagem_chat_shopee_integration_from_id_created_at
  ON public.mensagem_chat_shopee (installed_integration_id, from_id, created_at DESC)
  WHERE from_id IS NOT NULL;