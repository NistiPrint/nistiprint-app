-- ============================================
-- Migration: Demandas Overrides e Sugestões
-- ============================================
-- Permite personalização de campos herdados nas demandas
-- com rastreabilidade completa (quem, quando, por quê)
-- ============================================

-- 1. Criar tabela demandas_overrides
CREATE TABLE IF NOT EXISTS "public"."demandas_overrides" (
    "id" BIGSERIAL PRIMARY KEY,
    "demanda_id" BIGINT NOT NULL REFERENCES "public"."demandas_producao"("id") ON DELETE CASCADE,
    "campo" VARCHAR(50) NOT NULL,  -- 'horario_coleta', 'modalidade_logistica', etc.
    "valor_original" JSONB NOT NULL,  -- Valor herdado do canal
    "valor_alterado" JSONB NOT NULL,  -- Valor personalizado
    "justificativa" TEXT,  -- Motivo da alteração
    "justificativa_tipo" VARCHAR(50),  -- 'COLETA_ALTERNATIVA', 'MUDANCA_CLIENTE', etc.
    "usuario_id" INTEGER REFERENCES "public"."usuarios"("id"),
    "contexto_origem" VARCHAR(50),  -- 'PLANILHA', 'MULTIPLOS_PEDIDOS', 'DIRETA', 'CONSOLIDADA'
    "created_at" TIMESTAMPTZ DEFAULT NOW(),
    "updated_at" TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Comentários de documentação
COMMENT ON TABLE "public"."demandas_overrides" IS 
  'Registro de personalizações de campos herdados nas demandas.
   Permite que usuários personalizem valores sugeridos (horário, modalidade, etc.)
   com rastreabilidade completa de quem alterou, quando e por quê.';

COMMENT ON COLUMN "public"."demandas_overrides"."campo" IS 
  'Campo personalizado: horario_coleta, modalidade_logistica, data_limite_execucao, is_flex, fulfillment';

COMMENT ON COLUMN "public"."demandas_overrides"."justificativa_tipo" IS 
  'COLETA_ALTERNATIVA: Plataforma definiu horário alternativo no dia
   MUDANCA_CLIENTE: Solicitação do cliente
   ERRO_OPERACIONAL: Correção de erro operacional
   OTIMIZACAO_LOGISTICA: Melhoria operacional/logística
   OUTRO: Outro motivo';

COMMENT ON COLUMN "public"."demandas_overrides"."contexto_origem" IS 
  'Fonte de geração da demanda: PLANILHA, MULTIPLOS_PEDIDOS, DIRETA, CONSOLIDADA';

-- 3. Índices para performance
CREATE INDEX IF NOT EXISTS "idx_demandas_overrides_demanda" 
ON "public"."demandas_overrides"("demanda_id");

CREATE INDEX IF NOT EXISTS "idx_demandas_overrides_campo" 
ON "public"."demandas_overrides"("campo");

CREATE INDEX IF NOT EXISTS "idx_demandas_overrides_contexto" 
ON "public"."demandas_overrides"("contexto_origem");

CREATE INDEX IF NOT EXISTS "idx_demandas_overrides_usuario" 
ON "public"."demandas_overrides"("usuario_id");

-- 4. Trigger para updated_at
CREATE OR REPLACE TRIGGER "update_demandas_overrides_updated_at"
BEFORE UPDATE ON "public"."demandas_overrides"
FOR EACH ROW
EXECUTE FUNCTION "public"."update_updated_at_column"();

-- 5. Função para sugerir valores de demanda
CREATE OR REPLACE FUNCTION "public"."fn_sugerir_valores_demanda"(
    p_canal_venda_id INTEGER,
    p_tipo_demanda VARCHAR(50) DEFAULT 'PLATAFORMA',
    p_data_entrega DATE DEFAULT NULL
)
RETURNS TABLE (
    horario_coleta_sugerido TIME,
    modalidade_logistica_sugerida VARCHAR(20),
    data_limite_execucao_sugerida DATE,
    is_flex_sugerido BOOLEAN,
    fulfillment_sugerido BOOLEAN,
    prazo_dias INTEGER,
    horario_limite TIME,
    regra_origem VARCHAR(100),
    alertas JSONB
) AS $$
DECLARE
    v_horario_limite TIME;
    v_prioridade INTEGER;
    v_prazo_dias INTEGER;
    v_alertas JSONB := '[]'::jsonb;
BEGIN
    -- Buscar regra logística prioritária do canal
    SELECT 
        rl.horario_limite,
        rl.modalidade,
        CASE 
            WHEN rl.modalidade = 'EXPRESS' THEN 1
            WHEN rl.modalidade = 'STANDARD' THEN 2
            WHEN rl.modalidade = 'FULFILLMENT' THEN 3
            ELSE 4
        END as prioridade
    INTO 
        v_horario_limite,
        modalidade_logistica_sugerida,
        v_prioridade
    FROM "public"."regras_logisticas_canal" rl
    WHERE rl.canal_venda_id = p_canal_venda_id
    ORDER BY v_prioridade, rl.prioridade_uso
    LIMIT 1;

    -- Se encontrou regra
    IF modalidade_logistica_sugerida IS NOT NULL THEN
        horario_coleta_sugerido := v_horario_limite;
        horario_limite := v_horario_limite;
        regra_origem := 'regras_logisticas_canal';
        
        -- Calcular prazo em dias baseado na modalidade
        SELECT CASE 
            WHEN modalidade_logistica_sugerida = 'EXPRESS' THEN 1
            WHEN modalidade_logistica_sugerida = 'STANDARD' THEN 2
            WHEN modalidade_logistica_sugerida = 'FULFILLMENT' THEN 3
            ELSE 2
        END INTO v_prazo_dias;
        
        prazo_dias := v_prazo_dias;
        
        -- Calcular data limite de execução
        IF p_data_entrega IS NOT NULL THEN
            data_limite_execucao_sugerida := p_data_entrega - (v_prazo_dias || ' days')::INTERVAL;
        END IF;
        
        -- Adicionar alerta se horário for muito cedo/tarde
        IF v_horario_limite < '10:00'::time THEN
            v_alertas := v_alertas || '{"Horário de coleta muito cedo (< 10:00)"}'::jsonb;
        ELSIF v_horario_limite > '17:00'::time THEN
            v_alertas := v_alertas || '{"Horário de coleta tardio (> 17:00)"}'::jsonb;
        END IF;
    ELSE
        -- Sem regras logísticas: usar valores padrão
        horario_coleta_sugerido := '14:00'::time;
        horario_limite := '14:00'::time;
        modalidade_logistica_sugerida := 'STANDARD';
        prazo_dias := 2;
        regra_origem := 'padrao_sistema';
        v_alertas := '{"Canal sem regras logísticas definidas"}'::jsonb;
    END IF;
    
    -- Herdar flags do canal
    SELECT 
        COALESCE(cv.flex, false),
        COALESCE(cv.fulfillment, false)
    INTO 
        is_flex_sugerido,
        fulfillment_sugerido
    FROM "public"."canais_venda" cv
    WHERE cv.id = p_canal_venda_id;
    
    -- Se não encontrou canal
    IF is_flex_sugerido IS NULL THEN
        is_flex_sugerido := false;
        fulfillment_sugerido := false;
    END IF;
    
    alertas := v_alertas;
    
    RETURN QUERY SELECT 
        horario_coleta_sugerido,
        modalidade_logistica_sugerida,
        data_limite_execucao_sugerida,
        is_flex_sugerido,
        fulfillment_sugerido,
        prazo_dias,
        horario_limite,
        regra_origem,
        alertas;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION "public"."fn_sugerir_valores_demanda" IS 
  'Calcula valores sugeridos para criação de demanda baseados no canal de venda.
   Retorna: horário de coleta, modalidade logística, data limite, flags e alertas.
   Usado por todas as fontes de geração de demanda (planilha, múltiplos pedidos, direta).';

-- 6. Função para validar override
CREATE OR REPLACE FUNCTION "public"."fn_validar_override_demanda"(
    p_campo VARCHAR(50),
    p_valor_alterado JSONB,
    p_canal_venda_id INTEGER
)
RETURNS TABLE (
    valid BOOLEAN,
    alertas JSONB,
    bloqueios JSONB
) AS $$
DECLARE
    v_alertas JSONB := '[]'::jsonb;
    v_bloqueios JSONB := '[]'::jsonb;
    v_valid BOOLEAN := true;
    v_horario_limite TIME;
    v_valor_time TIME;
BEGIN
    -- Buscar horário limite do canal
    SELECT MAX(rl.horario_limite) INTO v_horario_limite
    FROM "public"."regras_logisticas_canal" rl
    WHERE rl.canal_venda_id = p_canal_venda_id
      AND rl.is_active = true;
    
    -- Validação por campo
    IF p_campo = 'horario_coleta' THEN
        -- Converter JSONB para TIME
        BEGIN
            v_valor_time := (p_valor_alterado #>> '{}')::time;
        EXCEPTION WHEN OTHERS THEN
            v_valid := false;
            v_bloqueios := v_bloqueios || '{"Formato de horário inválido"}'::jsonb;
        END;
        
        -- Verificar se está dentro do expediente
        IF v_valid AND (v_valor_time < '08:00'::time OR v_valor_time > '18:00'::time) THEN
            v_bloqueios := v_bloqueios || '{"Horário fora do expediente (08:00-18:00)"}'::jsonb;
        END IF;
        
        -- Alerta se após horário limite
        IF v_valid AND v_horario_limite IS NOT NULL AND v_valor_time > v_horario_limite THEN
            v_alertas := v_alertas || format('{"Horário após limite de coleta (%s)"}', v_horario_limite)::jsonb;
        END IF;
        
    ELSIF p_campo = 'modalidade_logistica' THEN
        -- Verificar se modalidade existe nas regras do canal
        IF NOT EXISTS (
            SELECT 1 FROM "public"."regras_logisticas_canal" rl
            WHERE rl.canal_venda_id = p_canal_venda_id
              AND rl.modalidade = (p_valor_alterado #>> '{}')
        ) THEN
            v_alertas := v_alertas || '{"Modalidade não existe nas regras do canal"}'::jsonb;
        END IF;
        
    ELSIF p_campo = 'data_limite_execucao' THEN
        -- Verificar se data não é muito próxima
        IF (p_valor_alterado #>> '{}')::date < CURRENT_DATE THEN
            v_bloqueios := v_bloqueios || '{"Data limite não pode ser no passado"}'::jsonb;
        END IF;
        
    ELSIF p_campo IN ('is_flex', 'fulfillment') THEN
        -- Flags podem ser alteradas livremente, apenas alerta
        v_alertas := v_alertas || '{"Alteração pode impactar logística"}'::jsonb;
    END IF;
    
    valid := v_valid AND jsonb_array_length(v_bloqueios) = 0;
    alertas := v_alertas;
    bloqueios := v_bloqueios;
    
    RETURN QUERY SELECT valid, alertas, bloqueios;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION "public"."fn_validar_override_demanda" IS 
  'Valida se um override de campo é compatível com as regras do canal.
   Retorna: valid (boolean), alertas (JSONB), bloqueios (JSONB).';

-- 7. RLS (Row Level Security)
ALTER TABLE "public"."demandas_overrides" ENABLE ROW LEVEL SECURITY;

-- Policy para leitura
DROP POLICY IF EXISTS "Usuários autenticados podem ver demandas_overrides"
    ON "public"."demandas_overrides";
CREATE POLICY "Usuários autenticados podem ver demandas_overrides"
    ON "public"."demandas_overrides"
    FOR SELECT
    TO authenticated
    USING (true);

-- Policy para inserção
DROP POLICY IF EXISTS "Usuários autenticados podem criar demandas_overrides"
    ON "public"."demandas_overrides";
CREATE POLICY "Usuários autenticados podem criar demandas_overrides"
    ON "public"."demandas_overrides"
    FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Policy para atualização
DROP POLICY IF EXISTS "Usuários autenticados podem atualizar demandas_overrides"
    ON "public"."demandas_overrides";
CREATE POLICY "Usuários autenticados podem atualizar demandas_overrides"
    ON "public"."demandas_overrides"
    FOR UPDATE
    TO authenticated
    USING (true);

-- Policy para exclusão
DROP POLICY IF EXISTS "Usuários autenticados podem deletar demandas_overrides"
    ON "public"."demandas_overrides";
CREATE POLICY "Usuários autenticados podem deletar demandas_overrides"
    ON "public"."demandas_overrides"
    FOR DELETE
    TO authenticated
    USING (true);

-- 8. Grants
GRANT ALL ON TABLE "public"."demandas_overrides" TO anon;
GRANT ALL ON TABLE "public"."demandas_overrides" TO authenticated;
GRANT ALL ON TABLE "public"."demandas_overrides" TO service_role;
GRANT EXECUTE ON FUNCTION "public"."fn_sugerir_valores_demanda" TO anon;
GRANT EXECUTE ON FUNCTION "public"."fn_sugerir_valores_demanda" TO authenticated;
GRANT EXECUTE ON FUNCTION "public"."fn_sugerir_valores_demanda" TO service_role;
GRANT EXECUTE ON FUNCTION "public"."fn_validar_override_demanda" TO anon;
GRANT EXECUTE ON FUNCTION "public"."fn_validar_override_demanda" TO authenticated;
GRANT EXECUTE ON FUNCTION "public"."fn_validar_override_demanda" TO service_role;
