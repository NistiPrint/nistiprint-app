-- Migração: Atualizar view_vendas_personalizadas_v3 para usar colunas explícitas
-- Data: 2026-04-12
-- Objetivo: Usar as novas colunas explícitas (buyer_username, shipping_carrier, etc)
--           em vez de navegar no JSON informacoes_cliente

DROP VIEW IF EXISTS "public"."view_vendas_personalizadas_v3";

CREATE VIEW "public"."view_vendas_personalizadas_v3" AS
SELECT
    "p"."id",
    "p"."numero_pedido",
    "p"."codigo_pedido_externo" AS "numero_loja",
    "p"."data_venda" AS "data_pedido",
    "p"."informacoes_cliente" AS "contato",
    ("v_bling"."dados_brutos" -> 'contato'::"text") ->> 'nome'::"text" AS "nome_cliente",
    "v_bling"."id_na_plataforma" AS "bling_id",
    true AS "personalizado",
    false AS "deletado",
    COALESCE(("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text"), "p"."informacoes_cliente") AS "informacoes_comprador",
    ("v_shopee"."dados_brutos" ->> 'mensagem'::"text") AS "shopee_message",
    -- Usar coluna explícita buyer_username em vez do JSON
    COALESCE("p"."buyer_username", (("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text")) AS "buyer_username",
    (EXISTS (
        SELECT 1
        FROM "public"."mensagem_chat_shopee" "mcs"
        WHERE (
            ("mcs"."from_user_name" = COALESCE("p"."buyer_username", (("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text")))
            OR ("mcs"."to_user_name" = COALESCE("p"."buyer_username", (("v_shopee"."dados_brutos" -> 'informacoes_comprador'::"text") ->> 'username'::"text")))
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
                    WHERE "op"."shopee_order_sn" = "p"."codigo_pedido_externo"
                      AND "op"."item_description" = "ip"."descricao"
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
    -- Filtrar pedidos do canal Shopee (canal_venda_id = 1)
    "p"."canal_venda_id" = 1
    -- E que possuam pelo menos um item personalizado
    AND EXISTS (
        SELECT 1
        FROM "public"."itens_pedido" "ip"
        WHERE "ip"."pedido_id" = "p"."id"
          AND "ip"."personalizado" = true
    )
);
