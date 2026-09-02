-- Preserve full provider status payloads for marketplace/ERP ingests.
-- Mercado Livre can compose order/payment/shipping/substatus into values
-- that legitimately exceed 50 chars.
-- pedidos_legacy_compat depends on pedidos.* and must be recreated around
-- the column type change.

DROP VIEW IF EXISTS public.pedidos_legacy_compat;

ALTER TABLE public.pedidos
  ALTER COLUMN status_original TYPE TEXT;

CREATE OR REPLACE VIEW public.pedidos_legacy_compat
WITH (security_invoker = true)
AS
SELECT
  p.*,
  COALESCE(p.erp_integration_id, p.bling_integration_id) AS canonical_bling_integration_id,
  COALESCE(p.erp_store_id, p.bling_loja_id) AS canonical_bling_loja_id,
  COALESCE(p.erp_order_id, p.bling_order_id) AS canonical_bling_order_id,
  COALESCE(p.erp_order_number, p.bling_order_number, p.numero_pedido)
    AS canonical_bling_order_number
FROM public.pedidos p;
