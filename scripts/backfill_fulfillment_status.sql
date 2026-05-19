-- Script para sincronizar a flag is_fulfillment na tabela 'pedidos' 
-- com base na flag 'fulfillment_flag' da tabela 'pedidos_shopee'.

UPDATE public.pedidos p
SET is_fulfillment = true
FROM public.pedidos_shopee ps
WHERE p.pedido_shopee_id = ps.id
  AND ps.fulfillment_flag = 'fulfilled_by_shopee'
  AND (p.is_fulfillment IS FALSE OR p.is_fulfillment IS NULL);

-- Caso necessário, garantir que pedidos que não são fulfillment estejam marcados como false
UPDATE public.pedidos p
SET is_fulfillment = false
FROM public.pedidos_shopee ps
WHERE p.pedido_shopee_id = ps.id
  AND ps.fulfillment_flag != 'fulfilled_by_shopee'
  AND (p.is_fulfillment IS TRUE);

-- Opcional: Relatório de quantos foram corrigidos
-- SELECT count(*) FROM public.pedidos WHERE is_fulfillment = true;
