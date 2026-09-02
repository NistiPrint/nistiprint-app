-- ============================================
-- Migração: Corrigir view_vendas_personalizadas_v3 - match por item_pedido_id
-- Data: 2026-04-10
-- Objetivo: Usar item_pedido_id como chave primária de match, com fallback
--           por descricao para compatibilidade retroativa.
-- ============================================

CREATE OR REPLACE VIEW "public"."view_vendas_personalizadas_v3" AS
SELECT
    "p"."id",
    "p"."numero_pedido",
    "p"."codigo_pedido_externo" AS "numero_loja",
    "p"."data_venda" AS "data_pedido",
    "p"."informacoes_cliente" AS "contato",
    "v_bling"."id_na_plataforma" AS "bling_id",
    true AS "personalizado",
    false AS "deletado",
    COALESCE(("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text"), "p"."informacoes_cliente") AS "informacoes_comprador",
    ("v_shopee"."dados_brutos" ->> 'mensagem'::"text") AS "shopee_message",
    COALESCE(
        (("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text"),
        ("p"."cliente_nome")::"text"
    ) AS "buyer_username",
    (EXISTS (
        SELECT 1
        FROM "public"."mensagem_chat_shopee" "mcs"
        WHERE (
            ("mcs"."from_user_name" = COALESCE(
                (("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text"),
                ("p"."cliente_nome")::"text"
            ))
            OR ("mcs"."to_user_name" = COALESCE(
                (("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text"),
                ("p"."cliente_nome")::"text"
            ))
        )
    )) AS "has_chat_messages",
    COALESCE((
        SELECT "jsonb_agg"(
            "jsonb_build_object"(
                'id', "ip"."id",
                'codigo', "ip"."sku_externo",
                'descricao', "ip"."descricao",
                'quantidade', "ip"."quantidade",
                'valor', "ip"."preco_unitario",
                'unidade', 'UN',
                'personalizado', "ip"."personalizado",
                'produto', "jsonb_build_object"('id', "ip"."produto_id"),
                'personalizations', (
                    SELECT "jsonb_agg"(
                        "jsonb_build_object"(
                            'personalization_id', "op"."id",
                            'item_id', "op"."item_id",
                            'item_description', "op"."item_description",
                            'quantity_to_personalize', ("op"."metadata" ->> 'quantity_to_personalize')::integer,
                            'customization_name', "op"."customization_name",
                            'name_source_message_id', "op"."name_source_message_id",
                            'customization_initial', "op"."customization_initial",
                            'initial_source_message_id', ("op"."metadata" ->> 'initial_source_message_id'),
                            'status', "op"."status",
                            'reasoning', "op"."reasoning"
                        )
                    )
                    FROM "public"."personalizacoes_pedido" "op"
                    WHERE (
                        -- PRIORIDADE 1: Match direto por item_pedido_id (novo)
                        ("op"."item_pedido_id" = "ip"."id")
                        OR
                        -- PRIORIDADE 2: Fallback por descricao (retrocompatibilidade)
                        ("op"."item_pedido_id" IS NULL AND "op"."item_description" = "ip"."descricao")
                    )
                )
            )
            ORDER BY "ip"."id"
        ) AS "jsonb_agg"
        FROM "public"."itens_pedido" "ip"
        WHERE ("ip"."pedido_id" = "p"."id")
    ), '[]'::"jsonb") AS "itens"
FROM (
    (
        ("public"."pedidos" "p"
        LEFT JOIN "public"."vinculos_integracao_pedido" "v_bling" ON (
            ("p"."id" = "v_bling"."pedido_id")
            AND (("v_bling"."plataforma")::"text" = 'BLING'::"text")
        ))
        LEFT JOIN "public"."vinculos_integracao_pedido" "v_shopee" ON (
            ("p"."id" = "v_shopee"."pedido_id")
            AND (("v_shopee"."plataforma")::"text" = 'SHOPEE'::"text")
        )
    )
)
WHERE (
    -- Filtrar apenas pedidos com origem Shopee ou Bling
    "p"."origem" IN ('SHOPEE', 'BLING')
    -- E que possuam pelo menos um item personalizado
    AND EXISTS (
        SELECT 1
        FROM "public"."itens_pedido" "ip"
        WHERE "ip"."pedido_id" = "p"."id"
          AND "ip"."personalizado" = true
    )
);
