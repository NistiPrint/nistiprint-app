-- Migration: Add Shopee Full carrier fulfillment rule and backfill
-- Date: 2026-05-20

-- 1) Ensure Shopee fulfillment rule by shipping_carrier = Full
INSERT INTO public.fulfillment_classification_rules
    (canal_venda_id, campo, operador, padrao, is_fulfillment, modalidade, prioridade)
SELECT cv.id, 'shipping_carrier', 'EQUALS', 'Full', true, 'FULFILLMENT', 11
  FROM public.canais_venda cv
  JOIN public.plataformas p ON cv.plataforma_id = p.id
 WHERE lower(p.nome) = 'shopee'
   AND NOT EXISTS (
      SELECT 1
        FROM public.fulfillment_classification_rules fr
       WHERE fr.canal_venda_id = cv.id
         AND fr.campo = 'shipping_carrier'
         AND fr.operador = 'EQUALS'
         AND fr.padrao = 'Full'
   );

-- 2) Ensure Shopee fulfillment rule by fulfillment_flag = fulfilled_by_shopee
INSERT INTO public.fulfillment_classification_rules
    (canal_venda_id, campo, operador, padrao, is_fulfillment, modalidade, prioridade)
SELECT cv.id, 'fulfillment_flag', 'EQUALS', 'fulfilled_by_shopee', true, 'FULFILLMENT', 10
  FROM public.canais_venda cv
  JOIN public.plataformas p ON cv.plataforma_id = p.id
 WHERE lower(p.nome) = 'shopee'
   AND NOT EXISTS (
      SELECT 1
        FROM public.fulfillment_classification_rules fr
       WHERE fr.canal_venda_id = cv.id
         AND fr.campo = 'fulfillment_flag'
         AND fr.operador = 'EQUALS'
         AND fr.padrao = 'fulfilled_by_shopee'
   );

-- 3) Backfill pedidos.is_fulfillment for Shopee orders:
--    TRUE when shipping_carrier='Full' OR fulfillment_flag='fulfilled_by_shopee'
WITH shopee_orders AS (
    SELECT
        p.id AS pedido_id,
        ps.shipping_carrier,
        ps.fulfillment_flag
    FROM public.pedidos p
    LEFT JOIN public.pedidos_shopee ps
           ON ps.id = p.pedido_shopee_id
           OR ps.codigo_pedido = p.codigo_pedido_externo
    LEFT JOIN public.installed_integrations ii
           ON ii.id = p.marketplace_integration_id
    LEFT JOIN public.integration_modules im
           ON im.id = ii.module_id
    LEFT JOIN public.canais_venda cv
           ON cv.id = p.canal_venda_id
    LEFT JOIN public.plataformas pl
           ON pl.id = cv.plataforma_id
    WHERE
        lower(coalesce(im.slug, '')) = 'shopee'
        OR lower(coalesce(pl.nome, '')) = 'shopee'
        OR upper(coalesce(p.origem, '')) = 'SHOPEE'
)
UPDATE public.pedidos p
   SET is_fulfillment = (
       lower(coalesce(so.shipping_carrier, '')) = 'full'
       OR coalesce(so.fulfillment_flag, '') = 'fulfilled_by_shopee'
   ),
       updated_at = now()
  FROM shopee_orders so
 WHERE p.id = so.pedido_id;
