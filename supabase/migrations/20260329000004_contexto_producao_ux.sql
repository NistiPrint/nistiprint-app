-- ============================================
-- Contexto de Produção e Otimização de UX
-- ============================================
-- Data: 2026-03-29
-- Descrição: Cria tabelas para contexto unificado de produção,
-- regras de priorização, sinalizações de demanda, preferências de UX
-- e templates de observações.
-- ============================================

-- ============================================================================
-- 1. TABELA: contextos_producao
-- ============================================================================
-- Contexto unificado que sintetiza todas as relações para uma demanda/pedido.
-- Usado para ordenação inteligente de produção e visualização contextual.

CREATE TABLE IF NOT EXISTS "public"."contextos_producao" (
    "id" uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    "tipo" character varying(50) NOT NULL,  -- PEDIDO_UNICO, DEMANDA_CONSOLIDADA
    
    -- Vínculos
    "pedido_id" integer REFERENCES "public"."pedidos"("id") ON DELETE CASCADE,
    "demanda_id" integer REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE,
    "canal_venda_id" integer NOT NULL REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE,
    
    -- Snapshot dos dados relevantes (para performance e consulta rápida)
    "snapshot_plataforma" jsonb DEFAULT '{}'::jsonb,
    "snapshot_integracao" jsonb DEFAULT '{}'::jsonb,
    "snapshot_logistica" jsonb DEFAULT '{}'::jsonb,
    "snapshot_temporal" jsonb DEFAULT '{}'::jsonb,
    "snapshot_priorizacao" jsonb DEFAULT '{}'::jsonb,
    
    -- Controle
    "is_active" boolean DEFAULT true,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

-- Comentários
COMMENT ON TABLE "public"."contextos_producao" IS
'Contexto unificado de produção que sintetiza relações entre plataformas, canais, integrações, logística, pedidos e demandas';

COMMENT ON COLUMN "public"."contextos_producao"."tipo" IS
'Tipo de contexto: PEDIDO_UNICO (um pedido) ou DEMANDA_CONSOLIDADA (múltiplos pedidos consolidados)';

COMMENT ON COLUMN "public"."contextos_producao"."snapshot_plataforma" IS
'Snapshot: {nome, tipo, pedido_externo_id}';

COMMENT ON COLUMN "public"."contextos_producao"."snapshot_integracao" IS
'Snapshot: {marketplace_integration_id, bling_integration_id, bling_loja_id}';

COMMENT ON COLUMN "public"."contextos_producao"."snapshot_logistica" IS
'Snapshot: {modalidade, tipo_envio, ponto_coleta_id, ponto_coleta_nome, horario_corte, is_flex, is_fulfillment}';

COMMENT ON COLUMN "public"."contextos_producao"."snapshot_temporal" IS
'Snapshot: {data_pedido, data_limite_envio, data_promessa_cliente, categoria_temporal, deadline_final}';

COMMENT ON COLUMN "public"."contextos_producao"."snapshot_priorizacao" IS
'Snapshot: {score, fatores, prioridade_manual}';

-- Índices para performance
CREATE INDEX IF NOT EXISTS "idx_contextos_producao_demanda_id"
ON "public"."contextos_producao"("demanda_id")
WHERE "is_active" = true;

CREATE INDEX IF NOT EXISTS "idx_contextos_producao_pedido_id"
ON "public"."contextos_producao"("pedido_id")
WHERE "is_active" = true;

CREATE INDEX IF NOT EXISTS "idx_contextos_producao_canal_id"
ON "public"."contextos_producao"("canal_venda_id")
WHERE "is_active" = true;

CREATE INDEX IF NOT EXISTS "idx_contextos_producao_tipo"
ON "public"."contextos_producao"("tipo");

-- Índice composto para ordenação de produção
CREATE INDEX IF NOT EXISTS "idx_contextos_producao_ordenacao"
ON "public"."contextos_producao"(
    "canal_venda_id",
    "created_at" DESC
)
WHERE "is_active" = true;

-- Trigger para atualizar updated_at
CREATE OR REPLACE TRIGGER "update_contextos_producao_updated_at"
BEFORE UPDATE ON "public"."contextos_producao"
FOR EACH ROW
EXECUTE FUNCTION "public"."update_updated_at_column"();


-- ============================================================================
-- 2. TABELA: regras_priorizacao
-- ============================================================================
-- Regras configuráveis para ordenação de produção.
-- Permite definir critérios de priorização sem hard-code.

CREATE TABLE IF NOT EXISTS "public"."regras_priorizacao" (
    "id" serial PRIMARY KEY,
    "nome" character varying(255) NOT NULL,
    "descricao" text,
    "condicoes" jsonb NOT NULL,
    "acao" jsonb NOT NULL,
    "ativa" boolean DEFAULT true,
    "prioridade_regra" integer DEFAULT 0,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

-- Comentários
COMMENT ON TABLE "public"."regras_priorizacao" IS
'Regras configuráveis para priorização e ordenação de demandas de produção';

COMMENT ON COLUMN "public"."regras_priorizacao"."condicoes" IS
'Condições para aplicar a regra: {canal_venda_ids, plataforma_nomes, modalidade_logistica, tipo_demanda, faixa_quantidade, horario_corte}';

COMMENT ON COLUMN "public"."regras_priorizacao"."acao" IS
'Ação de priorização: {tipo: ADD_SCORE|SET_PRIORIDADE|MOVER_TOPO|ADIAR, valor, fatores}';

COMMENT ON COLUMN "public"."regras_priorizacao"."prioridade_regra" IS
'Prioridade da regra para resolver conflitos (maior = mais prioritária)';

-- Índice para regras ativas ordenadas por prioridade
CREATE INDEX IF NOT EXISTS "idx_regras_priorizacao_ativas"
ON "public"."regras_priorizacao"("ativa", "prioridade_regra" DESC)
WHERE "ativa" = true;

-- Trigger para atualizar updated_at
CREATE OR REPLACE TRIGGER "update_regras_priorizacao_updated_at"
BEFORE UPDATE ON "public"."regras_priorizacao"
FOR EACH ROW
EXECUTE FUNCTION "public"."update_updated_at_column"();


-- ============================================================================
-- 3. TABELA: sinalizacoes_demanda
-- ============================================================================
-- Sinalizações visuais para demandas (alertas, badges, indicadores).
-- Usado para guiar o usuário com informações contextuais relevantes.

CREATE TABLE IF NOT EXISTS "public"."sinalizacoes_demanda" (
    "id" serial PRIMARY KEY,
    "demanda_id" integer NOT NULL REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE,
    "tipo" character varying(50) NOT NULL,
    "severidade" character varying(20) NOT NULL,
    "dados" jsonb DEFAULT '{}'::jsonb,
    "visivel" boolean DEFAULT true,
    "lido" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

-- Comentários
COMMENT ON TABLE "public"."sinalizacoes_demanda" IS
'Sinalizações visuais para demandas (alertas, badges, indicadores de contexto)';

COMMENT ON COLUMN "public"."sinalizacoes_demanda"."tipo" IS
'Tipo: FLEX, FULFILLMENT, HORARIO_CORTE_PROXIMO, PEDIDO_VINCULADO, INTEGRACAO_ERRO, ESTOQUE_INSUFICIENTE, PRODUCAO_ATRASADA';

COMMENT ON COLUMN "public"."sinalizacoes_demanda"."severidade" IS
'Severidade: INFO, ATENCAO, CRITICO';

COMMENT ON COLUMN "public"."sinalizacoes_demanda"."dados" IS
'Dados contextuais específicos do tipo de sinalização';

-- Índices para performance
CREATE INDEX IF NOT EXISTS "idx_sinalizacoes_demanda_id"
ON "public"."sinalizacoes_demanda"("demanda_id")
WHERE "visivel" = true;

CREATE INDEX IF NOT EXISTS "idx_sinalizacoes_demanda_tipo"
ON "public"."sinalizacoes_demanda"("tipo", "severidade")
WHERE "visivel" = true;

CREATE INDEX IF NOT EXISTS "idx_sinalizacoes_demanda_nao_lidas"
ON "public"."sinalizacoes_demanda"("demanda_id")
WHERE "visivel" = true AND "lido" = false;


-- ============================================================================
-- 4. TABELA: preferencias_ux_usuario
-- ============================================================================
-- Preferências de UX por usuário para personalizar a experiência.
-- Minimiza carga cognitiva ao lembrar configurações do usuário.

CREATE TABLE IF NOT EXISTS "public"."preferencias_ux_usuario" (
    "id" uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    "user_id" character varying(255) NOT NULL UNIQUE,
    "vista_padrao" character varying(50) DEFAULT 'KANBAN',
    "ordenacao_padrao" character varying(50) DEFAULT 'PRIORIDADE',
    "agrupamento_padrao" character varying(50),
    "filtros_salvos" jsonb DEFAULT '[]'::jsonb,
    "atalhos_personalizados" jsonb,
    "auto_fill_enabled" boolean DEFAULT true,
    "show_suggestions" boolean DEFAULT true,
    "validate_on_blur" boolean DEFAULT true,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

-- Comentários
COMMENT ON TABLE "public"."preferencias_ux_usuario" IS
'Preferências de UX por usuário para personalizar a experiência e reduzir carga cognitiva';

COMMENT ON COLUMN "public"."preferencias_ux_usuario"."vista_padrao" IS
'Vista padrão: KANBAN, LISTA, CALENDARIO';

COMMENT ON COLUMN "public"."preferencias_ux_usuario"."ordenacao_padrao" IS
'Ordenação padrão: PRIORIDADE, HORARIO_CORTE, DATA_ENTREGA, DATA_CRIACAO';

COMMENT ON COLUMN "public"."preferencias_ux_usuario"."agrupamento_padrao" IS
'Agrupamento padrão: CANAL, MODALIDADE, SETOR, STATUS';

COMMENT ON COLUMN "public"."preferencias_ux_usuario"."filtros_salvos" IS
'Lista de presets de filtros salvos pelo usuário';

COMMENT ON COLUMN "public"."preferencias_ux_usuario"."atalhos_personalizados" IS
'Mapeamento de atalhos de teclado personalizados';

COMMENT ON COLUMN "public"."preferencias_ux_usuario"."auto_fill_enabled" IS
'Habilitar autopreenchimento inteligente de formulários';

-- Índice para busca rápida por usuário
CREATE UNIQUE INDEX IF NOT EXISTS "idx_preferencias_ux_user_id"
ON "public"."preferencias_ux_usuario"("user_id");

-- Trigger para atualizar updated_at
CREATE OR REPLACE TRIGGER "update_preferencias_ux_usuario_updated_at"
BEFORE UPDATE ON "public"."preferencias_ux_usuario"
FOR EACH ROW
EXECUTE FUNCTION "public"."update_updated_at_column"();


-- ============================================================================
-- 5. TABELA: templates_obs_canal
-- ============================================================================
-- Templates de observações pré-configurados por canal de venda.
-- Usado para autopreenchimento de observações na criação de demandas.

CREATE TABLE IF NOT EXISTS "public"."templates_obs_canal" (
    "id" serial PRIMARY KEY,
    "canal_venda_id" integer REFERENCES "public"."canais_venda"("id") ON DELETE CASCADE,
    "nome" character varying(255) NOT NULL,
    "template" text NOT NULL,
    "variaveis_suportadas" text[] DEFAULT ARRAY[]::text[],
    "is_default" boolean DEFAULT false,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    
    -- Um canal só pode ter um template default
    UNIQUE("canal_venda_id", "is_default")
);

-- Comentários
COMMENT ON TABLE "public"."templates_obs_canal" IS
'Templates de observações pré-configurados por canal de venda para autopreenchimento';

COMMENT ON COLUMN "public"."templates_obs_canal"."template" IS
'Template de texto com variáveis substituíveis (ex: {{pedido_numero}}, {{data_entrega}})';

COMMENT ON COLUMN "public"."templates_obs_canal"."variaveis_suportadas" IS
'Lista de variáveis suportadas no template';

COMMENT ON COLUMN "public"."templates_obs_canal"."is_default" IS
'Indica se este é o template padrão para o canal (apenas um por canal)';

-- Índice para busca por canal
CREATE INDEX IF NOT EXISTS "idx_templates_obs_canal_id"
ON "public"."templates_obs_canal"("canal_venda_id")
WHERE "is_default" = true;

CREATE INDEX IF NOT EXISTS "idx_templates_obs_canal_nome"
ON "public"."templates_obs_canal"("canal_venda_id", "nome");

-- Trigger para atualizar updated_at
CREATE OR REPLACE TRIGGER "update_templates_obs_canal_updated_at"
BEFORE UPDATE ON "public"."templates_obs_canal"
FOR EACH ROW
EXECUTE FUNCTION "public"."update_updated_at_column"();


-- ============================================================================
-- 6. ÍNDICES ADICIONAIS DE PERFORMANCE
-- ============================================================================

-- Índice para ordenação de demandas (usado na listagem de produção)
CREATE INDEX IF NOT EXISTS "idx_demandas_priorizacao_ordenacao"
ON "public"."demandas_producao"(
    "prioridade_manual" DESC,
    "prioridade" DESC,
    "data_entrega" ASC,
    "horario_coleta" ASC
)
WHERE "status" IN ('AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL');

-- Índice para filtro por contexto logístico
CREATE INDEX IF NOT EXISTS "idx_demandas_contexto_logistico"
ON "public"."demandas_producao"(
    "canal_venda_id",
    "modalidade_logistica",
    "is_flex",
    "fulfillment"
);

-- Índice para regras logísticas por canal (usado no autopreenchimento)
CREATE INDEX IF NOT EXISTS "idx_regras_logisticas_canal_busca"
ON "public"."regras_logisticas_canal"(
    "canal_venda_id",
    "modalidade",
    "prioridade_uso" DESC
);


-- ============================================================================
-- 7. PERMISSÕES (RLS desativado para tabelas de configuração)
-- ============================================================================

ALTER TABLE "public"."contextos_producao" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."regras_priorizacao" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."sinalizacoes_demanda" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."preferencias_ux_usuario" DISABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."templates_obs_canal" DISABLE ROW LEVEL SECURITY;

-- Grants padrão
GRANT ALL ON TABLE "public"."contextos_producao" TO "anon";
GRANT ALL ON TABLE "public"."contextos_producao" TO "authenticated";
GRANT ALL ON TABLE "public"."contextos_producao" TO "service_role";

GRANT ALL ON TABLE "public"."regras_priorizacao" TO "anon";
GRANT ALL ON TABLE "public"."regras_priorizacao" TO "authenticated";
GRANT ALL ON TABLE "public"."regras_priorizacao" TO "service_role";

GRANT ALL ON TABLE "public"."sinalizacoes_demanda" TO "anon";
GRANT ALL ON TABLE "public"."sinalizacoes_demanda" TO "authenticated";
GRANT ALL ON TABLE "public"."sinalizacoes_demanda" TO "service_role";

GRANT ALL ON TABLE "public"."preferencias_ux_usuario" TO "anon";
GRANT ALL ON TABLE "public"."preferencias_ux_usuario" TO "authenticated";
GRANT ALL ON TABLE "public"."preferencias_ux_usuario" TO "service_role";

GRANT ALL ON TABLE "public"."templates_obs_canal" TO "anon";
GRANT ALL ON TABLE "public"."templates_obs_canal" TO "authenticated";
GRANT ALL ON TABLE "public"."templates_obs_canal" TO "service_role";

-- Grants para sequências
GRANT ALL ON SEQUENCE "public"."regras_priorizacao_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."regras_priorizacao_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."regras_priorizacao_id_seq" TO "service_role";

GRANT ALL ON SEQUENCE "public"."sinalizacoes_demanda_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."sinalizacoes_demanda_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."sinalizacoes_demanda_id_seq" TO "service_role";

GRANT ALL ON SEQUENCE "public"."templates_obs_canal_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."templates_obs_canal_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."templates_obs_canal_id_seq" TO "service_role";


-- ============================================================================
-- 8. DADOS INICIAIS (Regras de Priorização Padrão)
-- ============================================================================

-- Regra 1: Pedidos FLEX têm prioridade máxima
INSERT INTO "public"."regras_priorizacao" ("nome", "descricao", "condicoes", "acao", "ativa", "prioridade_regra")
VALUES (
    'Prioridade FLEX',
    'Pedidos com modalidade EXPRESS (FLEX) recebem prioridade máxima para entrega no mesmo dia',
    '{"modalidade_logistica": ["EXPRESS"], "is_flex": true}'::jsonb,
    '{"tipo": "ADD_SCORE", "valor": 100, "fatores": ["FLEX"]}'::jsonb,
    true,
    100
) ON CONFLICT DO NOTHING;

-- Regra 2: Horário de corte próximo
INSERT INTO "public"."regras_priorizacao" ("nome", "descricao", "condicoes", "acao", "ativa", "prioridade_regra")
VALUES (
    'Horário de Corte Próximo',
    'Demandas com horário de corte nas próximas 2 horas ganham prioridade',
    '{"horario_corte": {"antes": "18:00", "depois": "08:00"}}'::jsonb,
    '{"tipo": "ADD_SCORE", "valor": 50, "fatores": ["HORARIO_CORTE_PROXIMO"]}'::jsonb,
    true,
    90
) ON CONFLICT DO NOTHING;

-- Regra 3: Fulfillment
INSERT INTO "public"."regras_priorizacao" ("nome", "descricao", "condicoes", "acao", "ativa", "prioridade_regra")
VALUES (
    'Prioridade Fulfillment',
    'Reposição de fulfillment tem prioridade alta para manter estoque externo',
    '{"tipo_demanda": ["FULFILLMENT"]}'::jsonb,
    '{"tipo": "ADD_SCORE", "valor": 75, "fatores": ["FULFILLMENT"]}'::jsonb,
    true,
    85
) ON CONFLICT DO NOTHING;

-- Regra 4: B2B corporativo
INSERT INTO "public"."regras_priorizacao" ("nome", "descricao", "condicoes", "acao", "ativa", "prioridade_regra")
VALUES (
    'Prioridade B2B',
    'Vendas corporativas (B2B) têm prioridade moderada',
    '{"classificacao_cliente": ["B2B"]}'::jsonb,
    '{"tipo": "ADD_SCORE", "valor": 40, "fatores": ["B2B"]}'::jsonb,
    true,
    70
) ON CONFLICT DO NOTHING;


-- ============================================================================
-- 9. FUNÇÕES UTILITÁRIAS
-- ============================================================================

-- Função para categorizar demanda temporalmente
CREATE OR REPLACE FUNCTION "public"."categorizar_demanda_temporal"(
    p_data_entrega date,
    p_horario_coleta time
)
RETURNS text AS $$
DECLARE
    v_hoje date := CURRENT_DATE;
    v_amanha date := CURRENT_DATE + INTERVAL '1 day';
    v_horario_atual time := CURRENT_TIME;
BEGIN
    -- URGENTE: Entrega hoje com horário de corte nas próximas 4 horas
    IF p_data_entrega = v_hoje AND (p_horario_coleta - v_horario_atual) <= INTERVAL '4 hours' THEN
        RETURN 'URGENTE';
    END IF;
    
    -- HOJE: Entrega hoje
    IF p_data_entrega = v_hoje THEN
        RETURN 'HOJE';
    END IF;
    
    -- AMANHÃ: Entrega amanhã
    IF p_data_entrega = v_amanha THEN
        RETURN 'AMANHA';
    END IF;
    
    -- FUTURO: Entrega em data futura
    RETURN 'FUTURO';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION "public"."categorizar_demanda_temporal" IS
'Categoriza demanda temporalmente: URGENTE, HOJE, AMANHA, FUTURO';


-- Função para calcular score de priorização base
CREATE OR REPLACE FUNCTION "public"."calcular_score_priorizacao_base"(
    p_modalidade_logistica text,
    p_is_flex boolean,
    p_fulfillment boolean,
    p_classificacao_cliente text,
    p_horario_coleta time,
    p_data_entrega date
)
RETURNS integer AS $$
DECLARE
    v_score integer := 0;
    v_hoje date := CURRENT_DATE;
    v_amanha date := CURRENT_DATE + INTERVAL '1 day';
BEGIN
    -- Score base por modalidade
    CASE p_modalidade_logistica
        WHEN 'EXPRESS' THEN v_score := v_score + 100;
        WHEN 'FULFILLMENT' THEN v_score := v_score + 75;
        WHEN 'STANDARD' THEN v_score := v_score + 25;
        WHEN 'RETIRADA' THEN v_score := v_score + 10;
    END CASE;
    
    -- Bônus FLEX
    IF p_is_flex THEN
        v_score := v_score + 50;
    END IF;
    
    -- Bônus Fulfillment
    IF p_fulfillment THEN
        v_score := v_score + 30;
    END IF;
    
    -- Bônus por classificação
    CASE p_classificacao_cliente
        WHEN 'B2B' THEN v_score := v_score + 20;
        WHEN 'INTERNO' THEN v_score := v_score + 5;
    END CASE;
    
    -- Bônus urgência temporal
    IF p_data_entrega = v_hoje THEN
        v_score := v_score + 80;
    ELSIF p_data_entrega = v_amanha THEN
        v_score := v_score + 40;
    END IF;
    
    -- Bônus horário de corte (quanto mais cedo, maior prioridade)
    IF p_horario_coleta IS NOT NULL THEN
        v_score := v_score + (24 - EXTRACT(HOUR FROM p_horario_coleta));
    END IF;
    
    RETURN v_score;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION "public"."calcular_score_priorizacao_base" IS
'Calcula score base de priorização baseado em modalidade, urgência e horário';
