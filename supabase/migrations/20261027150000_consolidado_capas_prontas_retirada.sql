-- A expedição só enxergava itens cuja capa estava "produzida" (capas_produzidas_qtd).
-- A etapa que libera a retirada é "Capas Prontas" (capas_prontas_retirada_qtd), a mesma
-- usada pelo dashboard da demanda e como limite de expedicao_capas_retiradas_qtd.
-- Item com capas prontas e miolos prontos nunca aparecia em "Para retirar".

DROP VIEW IF EXISTS public.view_consolidado_producao;

CREATE VIEW public.view_consolidado_producao AS
 SELECT "i"."id" AS "item_id",
    "i"."demanda_id",
    "d"."descricao" AS "demanda_nome",
    "d"."data_entrega",
    "d"."horario_coleta",
    "i"."sku",
    "i"."descricao" AS "item_nome",
    "i"."quantidade" AS "qtd_total",
    "i"."capas_impressas_qtd",
    "i"."capas_prontas_retirada_qtd" AS "capas_prontas",
    "i"."miolos_prontos_retirada_qtd" AS "miolos_prontos",
    COALESCE("i"."expedicao_capas_retiradas_qtd", 0) AS "expedicao_capas_retiradas_qtd",
    COALESCE("i"."expedicao_miolos_retirados_qtd", 0) AS "expedicao_miolos_retirados_qtd",
    CAST(LEAST(
        COALESCE("i"."capas_prontas_retirada_qtd", 0) - COALESCE("i"."expedicao_capas_retiradas_qtd", 0),
        COALESCE("i"."miolos_prontos_retirada_qtd", 0) - COALESCE("i"."expedicao_miolos_retirados_qtd", 0)
    ) AS numeric(15,4)) AS "match_disponivel",
    "d"."status" AS "demanda_status",
    "i"."status_item",
        CASE
            WHEN ("d"."prioridade_manual" >= 100) THEN 'URGENTE'::"text"
            WHEN "d"."is_flex" THEN 'FLEX'::"text"
            ELSE 'NORMAL'::"text"
        END AS "trilha",
    "d"."updated_at" AS "status_sincronia"
   FROM ("public"."itens_demanda" "i"
     JOIN "public"."demandas_producao" "d" ON (("i"."demanda_id" = "d"."id")))
  WHERE (("d"."status")::"text" <> ALL ((ARRAY['Finalizado'::character varying, 'Coletado'::character varying, 'Cancelado'::character varying])::"text"[]));

ALTER VIEW public.view_consolidado_producao SET (security_invoker = true);

GRANT ALL ON TABLE public.view_consolidado_producao TO anon;
GRANT ALL ON TABLE public.view_consolidado_producao TO authenticated;
GRANT ALL ON TABLE public.view_consolidado_producao TO service_role;
