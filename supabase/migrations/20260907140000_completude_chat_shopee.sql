-- Completude da conversa Shopee como estado explicito.
--
-- O push de SellerChat nao entrega o corpo das mensagens digitadas dentro da
-- sessao do chatbot: entrega um `bundle_message` cujo `content.messages` e uma
-- lista de IDs. Ate aqui esses IDs eram gravados e nunca resolvidos, e nada no
-- sistema sabia dizer se uma conversa estava inteira. Esta tabela responde a
-- pergunta "esta conversa esta completa?" e serve de fila de trabalho para a
-- reconciliacao.
--
-- A janela e de 7 dias em todo lugar: so interessa o pedido mais recente, que e
-- o que ainda precisa ser atendido. Bundle fora da janela nao gera pendencia.

CREATE TABLE IF NOT EXISTS public.conversas_chat_shopee (
    conversation_id bigint PRIMARY KEY,
    installed_integration_id bigint REFERENCES public.installed_integrations(id),
    buyer_user_id bigint,
    buyer_username text,
    mensagens_esperadas integer NOT NULL DEFAULT 0,
    mensagens_presentes integer NOT NULL DEFAULT 0,
    ids_nao_recuperados jsonb NOT NULL DEFAULT '[]'::jsonb,
    status_completude text NOT NULL DEFAULT 'pendente',
    ultima_mensagem_em timestamptz,
    sincronizada_em timestamptz,
    proxima_tentativa_em timestamptz,
    tentativas integer NOT NULL DEFAULT 0,
    ultimo_erro text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT conversas_chat_shopee_status_chk
        CHECK (status_completude IN ('completa', 'pendente', 'expirada', 'erro'))
);

COMMENT ON TABLE public.conversas_chat_shopee IS
    'Estado de completude por conversa do SellerChat. Uma conversa da Shopee e por comprador, nunca por pedido.';
COMMENT ON COLUMN public.conversas_chat_shopee.mensagens_esperadas IS
    'IDs distintos referenciados por bundle_message dentro da janela. E o que a Shopee afirma existir.';
COMMENT ON COLUMN public.conversas_chat_shopee.ids_nao_recuperados IS
    'IDs que a Shopee deixou de devolver (provavelmente ocultados apos 12h sem leitura). Perda declarada, nunca silenciosa.';

-- `mark_as_replied` avisa que a loja respondeu, mas nao diz o que. Ele nao cria
-- pendencia de bundle, entao precisa de um sinal proprio: sem isso o recalculo
-- marcaria a conversa como completa e a varredura nunca buscaria a resposta.
ALTER TABLE public.conversas_chat_shopee
    ADD COLUMN IF NOT EXISTS sincronizacao_solicitada_em timestamptz;

COMMENT ON COLUMN public.conversas_chat_shopee.sincronizacao_solicitada_em IS
    'Pedido de varredura completa vindo de fora do bundle (resposta da loja, backfill, gate da IA). A varredura limpa apos sincronizar.';

-- Fila de trabalho da varredura: so as pendentes, na ordem do vencimento.
CREATE INDEX IF NOT EXISTS ix_conversas_chat_shopee_pendentes
    ON public.conversas_chat_shopee (proxima_tentativa_em)
    WHERE status_completude IN ('pendente', 'erro');

CREATE INDEX IF NOT EXISTS ix_conversas_chat_shopee_solicitadas
    ON public.conversas_chat_shopee (sincronizacao_solicitada_em)
    WHERE sincronizacao_solicitada_em IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_conversas_chat_shopee_buyer
    ON public.conversas_chat_shopee (buyer_user_id)
    WHERE buyer_user_id IS NOT NULL;

ALTER TABLE public.conversas_chat_shopee ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE ON public.conversas_chat_shopee TO service_role;

-- A busca por conversa e por bundle e o caminho quente da reconciliacao.
CREATE INDEX IF NOT EXISTS ix_mensagem_chat_shopee_conversa
    ON public.mensagem_chat_shopee (conversation_id, created_timestamp DESC);


-- ---------------------------------------------------------------------------
-- Registro da conversa a cada mensagem.
--
-- O trigger nao conta nada: so garante que toda conversa vista exista na tabela
-- e que a chegada de um bundle reabra a conversa para avaliacao. A contagem,
-- que e cara, fica em recalcular_completude_conversa().
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.registrar_conversa_chat_shopee()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NEW.conversation_id IS NULL THEN
        RETURN NEW;
    END IF;

    INSERT INTO public.conversas_chat_shopee AS c (
        conversation_id, installed_integration_id, ultima_mensagem_em,
        status_completude, proxima_tentativa_em
    )
    VALUES (
        NEW.conversation_id, NEW.installed_integration_id, NEW.created_timestamp,
        'pendente', now()
    )
    ON CONFLICT (conversation_id) DO UPDATE SET
        installed_integration_id = COALESCE(
            EXCLUDED.installed_integration_id, c.installed_integration_id
        ),
        ultima_mensagem_em = GREATEST(
            COALESCE(c.ultima_mensagem_em, EXCLUDED.ultima_mensagem_em),
            COALESCE(EXCLUDED.ultima_mensagem_em, c.ultima_mensagem_em)
        ),
        -- Um bundle novo cria expectativa nova: reabre a conversa mesmo que ela
        -- estivesse completa ou expirada, e zera o backoff.
        status_completude = CASE
            WHEN NEW.type = 'bundle_message' THEN 'pendente'
            ELSE c.status_completude
        END,
        tentativas = CASE WHEN NEW.type = 'bundle_message' THEN 0 ELSE c.tentativas END,
        proxima_tentativa_em = CASE
            WHEN NEW.type = 'bundle_message' THEN now()
            ELSE c.proxima_tentativa_em
        END,
        updated_at = now();

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_registrar_conversa_chat_shopee ON public.mensagem_chat_shopee;
CREATE TRIGGER trg_registrar_conversa_chat_shopee
    AFTER INSERT OR UPDATE ON public.mensagem_chat_shopee
    FOR EACH ROW EXECUTE FUNCTION public.registrar_conversa_chat_shopee();


-- ---------------------------------------------------------------------------
-- Recalculo da completude.
--
-- Compara o que os bundles afirmam existir com o que esta gravado. Idempotente:
-- pode ser chamada quantas vezes quiser, inclusive pela varredura.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.recalcular_completude_conversa(
    p_conversation_id bigint,
    p_janela_dias integer DEFAULT 7,
    p_tentativa boolean DEFAULT false,
    p_sincronizou boolean DEFAULT false,
    p_erro text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_corte timestamptz := now() - make_interval(days => GREATEST(COALESCE(p_janela_dias, 7), 1));
    v_esperados text[];
    v_ausentes text[];
    v_presentes integer := 0;
    v_ultima timestamptz;
    v_integration bigint;
    v_tentativas integer := 0;
    v_status text;
    v_resultado jsonb;
BEGIN
    -- IDs que os bundles da janela afirmam existir.
    SELECT COALESCE(array_agg(DISTINCT ref), '{}')
      INTO v_esperados
      FROM public.mensagem_chat_shopee m
      CROSS JOIN LATERAL jsonb_array_elements_text(m.content -> 'messages') AS ref
     WHERE m.conversation_id = p_conversation_id
       AND m.type = 'bundle_message'
       AND jsonb_typeof(m.content -> 'messages') = 'array'
       AND m.created_timestamp >= v_corte;

    -- Dos esperados, quais nao estao gravados.
    SELECT COALESCE(array_agg(ref), '{}')
      INTO v_ausentes
      FROM unnest(v_esperados) AS ref
     WHERE NOT EXISTS (
         SELECT 1 FROM public.mensagem_chat_shopee f WHERE f.id = ref
     );

    SELECT count(*), max(m.created_timestamp), max(m.installed_integration_id)
      INTO v_presentes, v_ultima, v_integration
      FROM public.mensagem_chat_shopee m
     WHERE m.conversation_id = p_conversation_id
       AND m.created_timestamp >= v_corte;

    INSERT INTO public.conversas_chat_shopee (conversation_id, installed_integration_id)
    VALUES (p_conversation_id, v_integration)
    ON CONFLICT (conversation_id) DO NOTHING;

    SELECT tentativas INTO v_tentativas
      FROM public.conversas_chat_shopee
     WHERE conversation_id = p_conversation_id;

    v_tentativas := COALESCE(v_tentativas, 0) + (CASE WHEN p_tentativa THEN 1 ELSE 0 END);

    -- Sem ausentes a conversa esta inteira. Com ausentes, ela so vira perda
    -- declarada depois de ao menos uma tentativa real: uma conversa antiga
    -- recem-descoberta merece a primeira busca antes de ser dada como perdida.
    IF COALESCE(array_length(v_ausentes, 1), 0) = 0 THEN
        v_status := 'completa';
    ELSIF v_tentativas >= 1 AND (
            v_tentativas >= 5
            OR COALESCE(v_ultima, now()) < now() - interval '12 hours'
         ) THEN
        v_status := 'expirada';
    ELSIF p_erro IS NOT NULL THEN
        v_status := 'erro';
    ELSE
        v_status := 'pendente';
    END IF;

    UPDATE public.conversas_chat_shopee SET
        installed_integration_id = COALESCE(v_integration, installed_integration_id),
        mensagens_esperadas = COALESCE(array_length(v_esperados, 1), 0),
        mensagens_presentes = COALESCE(v_presentes, 0),
        ids_nao_recuperados = CASE
            WHEN v_status IN ('completa') THEN '[]'::jsonb
            ELSE to_jsonb(v_ausentes)
        END,
        status_completude = v_status,
        ultima_mensagem_em = COALESCE(v_ultima, ultima_mensagem_em),
        tentativas = CASE WHEN v_status = 'completa' THEN 0 ELSE v_tentativas END,
        sincronizada_em = CASE WHEN p_sincronizou THEN now() ELSE sincronizada_em END,
        ultimo_erro = CASE WHEN v_status = 'completa' THEN NULL ELSE p_erro END,
        -- Backoff exponencial limitado a 1h; conversa resolvida sai da fila.
        proxima_tentativa_em = CASE
            WHEN v_status IN ('completa', 'expirada') THEN NULL
            ELSE now() + make_interval(secs => LEAST(3600, 30 * power(2, LEAST(v_tentativas, 7))::integer))
        END,
        updated_at = now()
    WHERE conversation_id = p_conversation_id
    RETURNING jsonb_build_object(
        'conversation_id', conversation_id,
        'status_completude', status_completude,
        'mensagens_esperadas', mensagens_esperadas,
        'mensagens_presentes', mensagens_presentes,
        'ids_nao_recuperados', ids_nao_recuperados,
        'tentativas', tentativas,
        'proxima_tentativa_em', proxima_tentativa_em,
        'ultima_mensagem_em', ultima_mensagem_em
    ) INTO v_resultado;

    RETURN COALESCE(v_resultado, jsonb_build_object(
        'conversation_id', p_conversation_id, 'status_completude', 'pendente'
    ));
END;
$$;

GRANT EXECUTE ON FUNCTION public.recalcular_completude_conversa(bigint, integer, boolean, boolean, text)
    TO service_role;


-- ---------------------------------------------------------------------------
-- Semeadura: registra as conversas ja existentes e calcula a completude atual.
--
-- Todas as linhas de hoje sao comprador -> loja, entao `from_id` da mensagem
-- mais antiga identifica o comprador. Daqui para a frente quem grava a
-- identidade e o servico de ingest, que conhece o shop_id da integracao.
-- ---------------------------------------------------------------------------
INSERT INTO public.conversas_chat_shopee (
    conversation_id, installed_integration_id, buyer_user_id, buyer_username, ultima_mensagem_em
)
SELECT DISTINCT ON (m.conversation_id)
       m.conversation_id,
       m.installed_integration_id,
       m.from_id,
       m.from_user_name,
       max(m.created_timestamp) OVER (PARTITION BY m.conversation_id)
  FROM public.mensagem_chat_shopee m
 WHERE m.conversation_id IS NOT NULL
 ORDER BY m.conversation_id, m.created_timestamp ASC
ON CONFLICT (conversation_id) DO NOTHING;

SELECT public.recalcular_completude_conversa(conversation_id)
  FROM public.conversas_chat_shopee;


-- ---------------------------------------------------------------------------
-- A view deixa de esconder o bundle.
--
-- Bundle resolvido some sozinho (as filhas aparecem como mensagens de verdade).
-- Bundle nao resolvido vira um marcador visivel: e melhor a IA e o operador
-- verem "faltam 4 mensagens" do que decidirem sobre um silencio.
-- ---------------------------------------------------------------------------
-- security_invoker=true precisa ser repetido: CREATE OR REPLACE VIEW redefine
-- as reloptions, e perder essa opcao mudaria silenciosamente quem a view
-- avalia sob RLS.
CREATE OR REPLACE VIEW public.view_mensagens_chat_ai
WITH (security_invoker = true) AS
WITH parsed AS (
    SELECT m.id,
           m.from_user_name,
           m.to_user_name,
           COALESCE(m.created_at, (m.created_timestamp AT TIME ZONE 'America/Sao_Paulo')) AS created_at,
           COALESCE(NULLIF(m.type, ''), 'text') AS type,
           CASE
               WHEN jsonb_typeof(m.content) = 'string' THEN (m.content #>> '{}')::jsonb
               ELSE m.content
           END AS content_json
      FROM public.mensagem_chat_shopee m
), normalized AS (
    SELECT p.id,
           p.from_user_name,
           p.to_user_name,
           p.created_at,
           p.type,
           TRIM(BOTH FROM COALESCE(
               CASE WHEN p.type = 'text' THEN p.content_json ->> 'text' END,
               CASE WHEN p.type = 'new_faq' THEN p.content_json ->> 'opening' END,
               CASE WHEN p.type = 'notification' THEN p.content_json ->> 'notification_for_sender' END,
               CASE
                   WHEN p.type = 'bundle_message'
                    AND jsonb_typeof(p.content_json -> 'messages') = 'array'
                   THEN (
                       SELECT CASE
                           WHEN count(*) FILTER (WHERE f.id IS NULL) = 0 THEN NULL
                           ELSE '[' || count(*) FILTER (WHERE f.id IS NULL)
                                || ' mensagem(ns) do comprador ainda nao recuperada(s) da Shopee]'
                       END
                       FROM jsonb_array_elements_text(p.content_json -> 'messages') AS ref
                       LEFT JOIN public.mensagem_chat_shopee f ON f.id = ref
                   )
               END,
               CASE WHEN p.type = 'bundle_message' THEN NULL ELSE p.content_json ->> 'text' END,
               CASE WHEN p.type = 'bundle_message' THEN NULL ELSE p.content_json ->> 'url' END,
               CASE WHEN p.content_json ? 'sticker_id' THEN '[figurinha]' END,
               CASE WHEN p.type = 'bundle_message' THEN NULL
                    ELSE NULLIF(p.content_json::text, '{}') END
           )) AS display_content
      FROM parsed p
)
SELECT id,
       from_user_name,
       to_user_name,
       created_at,
       type,
       "left"(display_content, 1000) AS display_content
  FROM normalized n
 WHERE (type <> ALL (ARRAY[
           'faq_unsupported', 'faq_question_list',
           'faq_category_choice', 'faq_feedback_prompt'
       ]))
   AND COALESCE(display_content, '') <> '';
