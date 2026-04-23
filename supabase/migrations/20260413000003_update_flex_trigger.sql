-- Update FLEX trigger to use shipping_carrier from pedidos_shopee as source of truth for Shopee orders
-- Platform identification uses canal_venda.slug instead of pedido.origem for accuracy

CREATE OR REPLACE FUNCTION public.calcular_is_flex()
RETURNS TRIGGER AS $$
DECLARE
    servico_logistico TEXT;
    shopee_shipping_carrier TEXT;
    norm_servico TEXT;
BEGIN
    -- Check if this is a Shopee order (by canal_venda.slug or by having data in pedidos_shopee)
    IF EXISTS (
        SELECT 1 FROM canais_venda cv
        WHERE cv.id = NEW.canal_venda_id AND cv.slug = 'shopee'
    ) OR NEW.codigo_pedido_externo IN (
        SELECT codigo_pedido FROM pedidos_shopee WHERE codigo_pedido = NEW.codigo_pedido_externo
    ) THEN
        -- For Shopee, use shipping_carrier from pedidos_shopee
        SELECT shipping_carrier INTO shopee_shipping_carrier
        FROM pedidos_shopee
        WHERE codigo_pedido = NEW.codigo_pedido_externo;
        
        IF shopee_shipping_carrier IS NOT NULL AND shopee_shipping_carrier <> '' THEN
            norm_servico := UPPER(shopee_shipping_carrier);
            IF norm_servico LIKE '%ENTREGA RAPIDA%' OR norm_servico LIKE '%ENTREGARAPIDA%' THEN
                NEW.is_flex := TRUE;
            ELSE
                NEW.is_flex := FALSE;
            END IF;
            RETURN NEW;
        END IF;
    END IF;
    
    -- Fallback to original logic (servico_logistico)
    servico_logistico := NEW.servico_logistico;
    IF servico_logistico IS NOT NULL AND servico_logistico <> '' THEN
        norm_servico := UPPER(servico_logistico);
        IF norm_servico LIKE '%ENTREGA RAPIDA%' OR norm_servico LIKE '%ENTREGARAPIDA%' THEN
            NEW.is_flex := TRUE;
        ELSE
            NEW.is_flex := FALSE;
        END IF;
    ELSE
        NEW.is_flex := FALSE;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
