-- =====================================================
-- Migration: Adiciona coluna derivada is_flex baseada no servico_logistico
-- =====================================================
-- Data: 2026-03-29
-- Descrição:
--   - Cria função para calcular is_flex baseado no servico_logistico
--   - Cria trigger para atualizar is_flex automaticamente
--   - Atualiza pedidos existentes com base nos dados atuais
-- =====================================================
-- NOTA: shipping_carrier é dado logístico, não do cliente.
--       Deve ser armazenado em servico_logistico, NÃO em informacoes_cliente.
-- =====================================================

-- 1. Criar função para calcular is_flex baseado no servico_logistico
-- =====================================================
CREATE OR REPLACE FUNCTION public.calcular_is_flex()
RETURNS TRIGGER AS $$
DECLARE
    servico_logistico TEXT;
    norm_servico TEXT;
BEGIN
    -- Usar servico_logistico como fonte primária (dado logístico)
    servico_logistico := NEW.servico_logistico;
    
    -- Normalizar: converter para maiúsculas e remover acentos via REPLACE
    -- Nota: Usamos REPLACE em vez de UNACCENT para não depender de extensão
    IF servico_logistico IS NOT NULL AND servico_logistico <> '' THEN
        norm_servico := UPPER(servico_logistico);
        -- Remover acentos comuns em português (cada REPLACE remove um tipo de acento)
        norm_servico := REPLACE(norm_servico, 'Á', 'A');
        norm_servico := REPLACE(norm_servico, 'À', 'A');
        norm_servico := REPLACE(norm_servico, 'Ã', 'A');
        norm_servico := REPLACE(norm_servico, 'Â', 'A');
        norm_servico := REPLACE(norm_servico, 'É', 'E');
        norm_servico := REPLACE(norm_servico, 'È', 'E');
        norm_servico := REPLACE(norm_servico, 'Ê', 'E');
        norm_servico := REPLACE(norm_servico, 'Í', 'I');
        norm_servico := REPLACE(norm_servico, 'Ì', 'I');
        norm_servico := REPLACE(norm_servico, 'Î', 'I');
        norm_servico := REPLACE(norm_servico, 'Ó', 'O');
        norm_servico := REPLACE(norm_servico, 'Ò', 'O');
        norm_servico := REPLACE(norm_servico, 'Õ', 'O');
        norm_servico := REPLACE(norm_servico, 'Ô', 'O');
        norm_servico := REPLACE(norm_servico, 'Ú', 'U');
        norm_servico := REPLACE(norm_servico, 'Ù', 'U');
        norm_servico := REPLACE(norm_servico, 'Û', 'U');
        norm_servico := REPLACE(norm_servico, 'Ç', 'C');
        norm_servico := REPLACE(norm_servico, 'Ñ', 'N');
        
        -- Remover espaços e hífens para normalização
        norm_servico := REPLACE(norm_servico, ' ', '_');
        norm_servico := REPLACE(norm_servico, '-', '_');

        -- Verificar se contém termos de entrega rápida
        -- Termo principal: "ENTREGA RÁPIDA" (Shopee)
        IF norm_servico LIKE '%ENTREGA_RAPIDA%' OR norm_servico LIKE '%ENTREGARAPIDA%' THEN
            NEW.is_flex := TRUE;
        ELSE
            NEW.is_flex := FALSE;
        END IF;
    ELSE
        -- Sem servico_logistico, manter valor atual ou FALSE
        IF NEW.is_flex IS NULL THEN
            NEW.is_flex := FALSE;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Criar trigger para atualizar is_flex automaticamente
-- =====================================================
DROP TRIGGER IF EXISTS trg_calcular_is_flex ON public.pedidos;
CREATE TRIGGER trg_calcular_is_flex
    BEFORE INSERT OR UPDATE OF servico_logistico, is_flex
    ON public.pedidos
    FOR EACH ROW
    EXECUTE FUNCTION public.calcular_is_flex();

-- 3. Atualizar pedidos existentes com base nos dados atuais
-- =====================================================
-- Esta atualização vai percorrer todos os pedidos e calcular is_flex
-- com base no servico_logistico atual

-- Função auxiliar para normalizar texto (sem dependência de unaccent)
CREATE OR REPLACE FUNCTION public.normalize_text_for_flex(input_text TEXT)
RETURNS TEXT AS $$
DECLARE
    result TEXT;
BEGIN
    IF input_text IS NULL THEN
        RETURN NULL;
    END IF;
    
    -- Converter para maiúsculas
    result := UPPER(input_text);
    
    -- Remover acentos comuns em português (cada REPLACE remove um tipo de acento)
    result := REPLACE(result, 'Á', 'A');
    result := REPLACE(result, 'À', 'A');
    result := REPLACE(result, 'Ã', 'A');
    result := REPLACE(result, 'Â', 'A');
    result := REPLACE(result, 'É', 'E');
    result := REPLACE(result, 'È', 'E');
    result := REPLACE(result, 'Ê', 'E');
    result := REPLACE(result, 'Í', 'I');
    result := REPLACE(result, 'Ì', 'I');
    result := REPLACE(result, 'Î', 'I');
    result := REPLACE(result, 'Ó', 'O');
    result := REPLACE(result, 'Ò', 'O');
    result := REPLACE(result, 'Õ', 'O');
    result := REPLACE(result, 'Ô', 'O');
    result := REPLACE(result, 'Ú', 'U');
    result := REPLACE(result, 'Ù', 'U');
    result := REPLACE(result, 'Û', 'U');
    result := REPLACE(result, 'Ç', 'C');
    result := REPLACE(result, 'Ñ', 'N');
    
    -- Remover espaços e hífens
    result := REPLACE(result, ' ', '_');
    result := REPLACE(result, '-', '_');
    
    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- Atualizar pedidos que têm servico_logistico preenchido
UPDATE public.pedidos
SET is_flex = (
    CASE
        WHEN public.normalize_text_for_flex(servico_logistico) LIKE '%ENTREGA_RAPIDA%' 
             OR public.normalize_text_for_flex(servico_logistico) LIKE '%ENTREGARAPIDA%'
        THEN TRUE
        ELSE FALSE
    END
)
WHERE servico_logistico IS NOT NULL 
  AND servico_logistico <> '';

-- 4. Criar índice para otimizar consultas por is_flex (se não existir)
-- =====================================================
CREATE INDEX IF NOT EXISTS idx_pedidos_is_flex 
ON public.pedidos(is_flex) 
WHERE is_flex = TRUE;

-- 5. Adicionar comentário documentando a coluna derivada
-- =====================================================
COMMENT ON COLUMN public.pedidos.is_flex IS 
'Coluna derivada automaticamente baseada no servico_logistico. 
TRUE quando servico_logistico contém "Entrega Rápida" (Shopee Flex). 
Atualizada automaticamente pelo trigger trg_calcular_is_flex.';

COMMENT ON FUNCTION public.calcular_is_flex() IS 
'Função trigger que calcula automaticamente o valor de is_flex baseado no servico_logistico.
Define is_flex = TRUE quando servico_logistico contém "Entrega Rápida".';

-- =====================================================
-- RESUMO
-- =====================================================
-- ✅ Função calcular_is_flex() criada
-- ✅ Trigger trg_calcular_is_flex criado (BEFORE INSERT/UPDATE)
-- ✅ Pedidos existentes atualizados
-- ✅ Índice otimizado para consultas Flex
-- ✅ Documentação adicionada
-- =====================================================
-- Agora, sempre que um pedido for inserido ou atualizado com:
-- - servico_logistico preenchido
-- O campo is_flex será calculado automaticamente!
-- =====================================================
