-- Expose chat message timestamps as timezone-aware instants.
-- `created_at` is a legacy timestamp without timezone containing the UTC
-- wall-clock representation of `created_timestamp`.
DROP VIEW IF EXISTS public.view_mensagens_chat_ai_v2;

CREATE VIEW public.view_mensagens_chat_ai_v2
WITH (security_invoker = true) AS
SELECT m.id,
       m.installed_integration_id,
       m.from_id,
       m.to_id,
       m.from_user_name,
       m.to_user_name,
       m.conversation_id,
       COALESCE(
           m.created_timestamp,
           m.created_at AT TIME ZONE 'UTC'
       ) AS created_at,
       m.type,
       m.content,
       m.source_content,
       v.display_content
FROM public.mensagem_chat_shopee AS m
JOIN public.view_mensagens_chat_ai AS v ON v.id = m.id;

REVOKE ALL ON TABLE public.view_mensagens_chat_ai_v2 FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.view_mensagens_chat_ai_v2 TO service_role;
