-- =====================================================
-- Migration: Atualiza detecção de pedidos Flex no trigger (ESTRITO SHOPEE)
-- Data: 2026-03-30
-- Descrição:
--   - Torna detecção de is_flex estrita para "ENTREGA RÁPIDA"
--   - Garante que is_flex seja "sticky" (uma vez TRUE, não volta para FALSE via trigger)
-- =====================================================

CREATE OR REPLACE FUNCTION public.calcular_is_flex()
RETURNS TRIGGER AS $$
DECLARE
    servico_logistico TEXT;
    norm_servico TEXT;
    ja_era_flex BOOLEAN;
BEGIN
    -- Lógica Sticky: se já era flex, manter como TRUE.
    -- Isso evita que atualizações do Bling (que as vezes não mandam carrier)
    -- desativem o flag setado pela planilha Shopee.
    
    ja_era_flex := FALSE;
    
    -- Tenta pegar valor anterior se for UPDATE
    IF (TG_OP = 'UPDATE') THEN
        IF OLD.is_flex = TRUE THEN
            ja_era_flex := TRUE;
        END IF;
    END IF;
    
    -- Se NEW.is_flex vier como TRUE (ex: setado manualmente ou via mapper), respeitamos.
    IF NEW.is_flex = TRUE THEN
        ja_era_flex := TRUE;
    END IF;

    -- Usar servico_logistico como fonte de detecção
    servico_logistico := NEW.servico_logistico;
    
    IF servico_logistico IS NOT NULL AND servico_logistico <> '' THEN
        -- Normalização básica para busca
        norm_servico := UPPER(servico_logistico);
        
        -- Verificar EXCLUSIVAMENTE termos de Entrega Rápida da Shopee
        IF norm_servico LIKE '%ENTREGA_RAPIDA%' 
           OR norm_servico LIKE '%ENTREGARAPIDA%'
           OR norm_servico LIKE '%ENTREGA_RÁPIDA%'
           OR norm_servico LIKE '%ENTREGARÁPIDA%'
           OR norm_servico LIKE '%ENTREGA RAPIDA%'
           OR norm_servico LIKE '%ENTREGA RÁPIDA%'
        THEN
            NEW.is_flex := TRUE;
        ELSE
            -- Se NÃO detectou nos termos acima, mas JÁ ERA flex, manter TRUE
            IF ja_era_flex THEN
                NEW.is_flex := TRUE;
            ELSE
                NEW.is_flex := FALSE;
            END IF;
        END IF;
    ELSE
        -- Sem servico_logistico no NEW:
        -- Se ja_era_flex, mantém. Senão, se NEW.is_flex for NULL, define FALSE.
        IF ja_era_flex THEN
            NEW.is_flex := TRUE;
        ELSIF NEW.is_flex IS NULL THEN
            NEW.is_flex := FALSE;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Corrigir pedidos que possam ter sido marcados erroneamente por outros termos (DIRETA/SPX/etc)
-- se não contiverem explicitamente "ENTREGA RÁPIDA"
UPDATE public.pedidos
SET is_flex = FALSE
WHERE is_flex = TRUE 
  AND (servico_logistico IS NULL OR (
    UPPER(servico_logistico) NOT LIKE '%ENTREGA_RAPIDA%'
    AND UPPER(servico_logistico) NOT LIKE '%ENTREGARAPIDA%'
    AND UPPER(servico_logistico) NOT LIKE '%ENTREGA_RÁPIDA%'
    AND UPPER(servico_logistico) NOT LIKE '%ENTREGARÁPIDA%'
    AND UPPER(servico_logistico) NOT LIKE '%ENTREGA RAPIDA%'
    AND UPPER(servico_logistico) NOT LIKE '%ENTREGA RÁPIDA%'
  ));

COMMENT ON FUNCTION public.calcular_is_flex() IS 
'Função trigger que calcula automaticamente o valor de is_flex baseado no servico_logistico.
Estrito para: "Entrega Rápida" (Shopee).
Implementa lógica sticky: uma vez TRUE, o pedido permanece Flex.';
