-- Migration: 20260411000002_fix_match_disponivel_view.sql
-- Data: 2026-04-11
-- Objetivo: Corrigir cálculo de match_disponivel para considerar retiradas de expedição
-- 
-- Problema: Itens não saem da lista de expedição após retirada porque o cálculo
-- de match_disponivel não considera as quantidades já expedidas.
--
-- Solução: Atualizar view_consolidado_producao para subtrair as retiradas de
-- expedição (expedicao_capas_retiradas_qtd e expedicao_miolos_retirados_qtd)
-- do cálculo de match_disponivel.

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
    "i"."capas_produzidas_qtd" AS "capas_prontas",
    "i"."miolos_prontos_retirada_qtd" AS "miolos_prontos",
    COALESCE("i"."expedicao_capas_retiradas_qtd", 0) AS "expedicao_capas_retiradas_qtd",
    COALESCE("i"."expedicao_miolos_retirados_qtd", 0) AS "expedicao_miolos_retirados_qtd",
    CAST(LEAST(
        COALESCE("i"."capas_produzidas_qtd", 0) - COALESCE("i"."expedicao_capas_retiradas_qtd", 0),
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

-- Grants
GRANT ALL ON TABLE public.view_consolidado_producao TO anon;
GRANT ALL ON TABLE public.view_consolidado_producao TO authenticated;
GRANT ALL ON TABLE public.view_consolidado_producao TO service_role;

COMMENT ON VIEW public.view_consolidado_producao IS
'View consolidada de produção com cálculo corrigido de match_disponivel.
Agora considera as retiradas de expedição para determinar quantidades disponíveis para montagem.';
