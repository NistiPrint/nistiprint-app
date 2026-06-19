-- ============================================================
-- Migração: views e flags de reprocessamento para personalizados
-- Data: 2026-06-17
-- Objetivo:
-- - normalizar mensagens de chat para uso em UI/LLM
-- - expor flags de IA via views
-- - evitar reprocessamento sem mensagens novas do comprador
-- ============================================================

ALTER TABLE public.personalizacoes_pedido
    ADD COLUMN IF NOT EXISTS item_pedido_id integer;

CREATE INDEX IF NOT EXISTS idx_personalizacoes_item_pedido_id
    ON public.personalizacoes_pedido(item_pedido_id)
    WHERE item_pedido_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_logs_execucao_ia_order_sn_executed_at
    ON public.logs_execucao_ia(order_sn, executed_at DESC);

CREATE INDEX IF NOT EXISTS idx_mensagem_chat_shopee_created_at_desc
    ON public.mensagem_chat_shopee(created_at DESC);

CREATE OR REPLACE VIEW public.view_mensagens_chat_ai AS
WITH parsed AS (
    SELECT
        m.id,
        m.from_user_name,
        m.to_user_name,
        m.created_at,
        COALESCE(NULLIF(m.type, ''), 'text') AS type,
        CASE
            WHEN jsonb_typeof(m.content) = 'string' THEN (m.content #>> '{}')::jsonb
            ELSE m.content
        END AS content_json
    FROM public.mensagem_chat_shopee AS m
),
normalized AS (
    SELECT
        p.id,
        p.from_user_name,
        p.to_user_name,
        p.created_at,
        p.type,
        trim(
            COALESCE(
                CASE WHEN p.type = 'text' THEN p.content_json ->> 'text' END,
                CASE WHEN p.type = 'new_faq' THEN p.content_json ->> 'opening' END,
                CASE WHEN p.type = 'notification' THEN p.content_json ->> 'notification_for_sender' END,
                p.content_json ->> 'text',
                p.content_json ->> 'url',
                CASE WHEN p.content_json ? 'sticker_id' THEN '[figurinha]' END,
                NULLIF(p.content_json::text, '{}')
            )
        ) AS display_content
    FROM parsed AS p
)
SELECT
    n.id,
    n.from_user_name,
    n.to_user_name,
    n.created_at,
    n.type,
    left(n.display_content, 1000) AS display_content
FROM normalized AS n
WHERE n.type <> ALL (ARRAY[
    'faq_unsupported',
    'faq_question_list',
    'faq_category_choice',
    'faq_feedback_prompt',
    'bundle_message'
]::text[])
AND COALESCE(n.display_content, '') <> '';

CREATE OR REPLACE VIEW public.view_pedidos_personalizados_ai AS
WITH base_orders AS (
    SELECT
        p.id,
        p.numero_pedido,
        p.codigo_pedido_externo,
        p.data_venda,
        p.informacoes_cliente,
        p.cliente_nome,
        p.cliente_documento,
        p.cliente_telefone,
        p.cliente_email,
        p.is_flex,
        p.servico_logistico,
        ps.informacoes_comprador,
        ps.mensagem AS shopee_message,
        pb.bling_id,
        pb.raw_payload AS bling_raw_payload,
        COALESCE(
            ps.informacoes_comprador ->> 'username',
            ((ps.informacoes_comprador #>> '{}')::jsonb ->> 'username'),
            p.cliente_nome
        ) AS buyer_username
    FROM public.pedidos AS p
    INNER JOIN public.canais_venda AS cv
        ON cv.id = p.canal_venda_id
    LEFT JOIN public.pedidos_shopee AS ps
        ON ps.codigo_pedido = p.codigo_pedido_externo
    LEFT JOIN public.pedidos_bling AS pb
        ON pb.numero_pedido = p.numero_pedido
    WHERE cv.slug = 'shopee'
      AND EXISTS (
          SELECT 1
          FROM public.itens_pedido AS ip
          WHERE ip.pedido_id = p.id
            AND ip.personalizado = true
      )
),
latest_logs AS (
    SELECT DISTINCT ON (l.order_sn)
        l.order_sn,
        l.executed_at,
        l.status,
        l.metadata
    FROM public.logs_execucao_ia AS l
    ORDER BY l.order_sn, l.executed_at DESC, l.id DESC
),
chat_stats AS (
    SELECT
        bo.id AS pedido_id,
        max(vm.created_at) AS last_chat_message_at,
        max(vm.created_at) FILTER (
            WHERE vm.from_user_name = bo.buyer_username
        ) AS last_buyer_message_at
    FROM base_orders AS bo
    LEFT JOIN public.view_mensagens_chat_ai AS vm
        ON vm.from_user_name = bo.buyer_username
        OR vm.to_user_name = bo.buyer_username
    GROUP BY bo.id
),
item_personalizations AS (
    SELECT
        ip.pedido_id,
        jsonb_agg(
            jsonb_build_object(
                'id', ip.id,
                'codigo', ip.sku_externo,
                'descricao', ip.descricao,
                'quantidade', ip.quantidade,
                'valor', ip.preco_unitario,
                'unidade', 'UN',
                'personalizado', ip.personalizado,
                'produto', jsonb_build_object('id', ip.produto_id),
                'personalizations', COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'id', pp.id,
                            'item_pedido_id', pp.item_pedido_id,
                            'item_id', pp.item_id,
                            'item_description', pp.item_description,
                            'quantity_to_personalize',
                                COALESCE(
                                    NULLIF(pp.detalhes_personalizacao ->> 'quantity_to_personalize', '')::integer,
                                    NULLIF(pp.metadata ->> 'quantity_to_personalize', '')::integer,
                                    1
                                ),
                            'customization_name', pp.customization_name,
                            'name_source_message_id', pp.name_source_message_id,
                            'customization_initial', pp.customization_initial,
                            'initial_source_message_id',
                                COALESCE(
                                    pp.detalhes_personalizacao ->> 'initial_source_message_id',
                                    pp.metadata ->> 'initial_source_message_id'
                                ),
                            'status', pp.status,
                            'reasoning', pp.reasoning
                        )
                        ORDER BY pp.id
                    )
                    FROM public.personalizacoes_pedido AS pp
                    WHERE (
                        pp.item_pedido_id = ip.id
                        OR (
                            pp.item_pedido_id IS NULL
                            AND pp.shopee_order_sn = (
                                SELECT p2.codigo_pedido_externo
                                FROM public.pedidos AS p2
                                WHERE p2.id = ip.pedido_id
                            )
                            AND pp.item_description = ip.descricao
                        )
                    )
                ), '[]'::jsonb)
            )
            ORDER BY ip.id
        ) AS itens
    FROM public.itens_pedido AS ip
    WHERE ip.personalizado = true
    GROUP BY ip.pedido_id
)
SELECT
    bo.id,
    bo.numero_pedido,
    bo.codigo_pedido_externo AS numero_loja,
    bo.data_venda AS data_pedido,
    COALESCE(bo.informacoes_cliente, '{}'::jsonb) AS contato,
    COALESCE(
        bo.cliente_nome,
        bo.informacoes_cliente ->> 'nome',
        bo.informacoes_comprador ->> 'name'
    ) AS nome_cliente,
    bo.bling_id,
    true AS personalizado,
    false AS deletado,
    bo.informacoes_comprador,
    bo.shopee_message,
    bo.buyer_username,
    COALESCE(cs.last_chat_message_at IS NOT NULL, false) AS has_chat_messages,
    cs.last_chat_message_at,
    cs.last_buyer_message_at,
    ll.executed_at AS last_ai_executed_at,
    COALESCE(ll.status, 'NOT_PROCESSED') AS ai_status,
    CASE
        WHEN ll.executed_at IS NULL THEN true
        WHEN COALESCE(ll.status, '') IN ('error', 'db_error', 'no_response') THEN true
        WHEN cs.last_buyer_message_at IS NOT NULL AND cs.last_buyer_message_at > ll.executed_at THEN true
        ELSE false
    END AS needs_ai_processing,
    COALESCE(ip.itens, '[]'::jsonb) AS itens
FROM base_orders AS bo
LEFT JOIN chat_stats AS cs
    ON cs.pedido_id = bo.id
LEFT JOIN latest_logs AS ll
    ON ll.order_sn = bo.codigo_pedido_externo
LEFT JOIN item_personalizations AS ip
    ON ip.pedido_id = bo.id;

DROP VIEW IF EXISTS public.view_vendas_personalizadas_v3;

CREATE VIEW public.view_vendas_personalizadas_v3 AS
SELECT
    vpa.id,
    vpa.numero_pedido,
    vpa.numero_loja,
    vpa.data_pedido,
    vpa.contato,
    vpa.nome_cliente,
    vpa.bling_id,
    vpa.personalizado,
    vpa.deletado,
    vpa.informacoes_comprador,
    vpa.shopee_message,
    vpa.buyer_username,
    vpa.has_chat_messages,
    vpa.last_chat_message_at,
    vpa.last_buyer_message_at,
    vpa.last_ai_executed_at,
    vpa.ai_status,
    vpa.needs_ai_processing,
    vpa.itens
FROM public.view_pedidos_personalizados_ai AS vpa;

GRANT ALL ON TABLE public.view_vendas_personalizadas_v3 TO anon;
GRANT ALL ON TABLE public.view_vendas_personalizadas_v3 TO authenticated;
GRANT ALL ON TABLE public.view_vendas_personalizadas_v3 TO service_role;
