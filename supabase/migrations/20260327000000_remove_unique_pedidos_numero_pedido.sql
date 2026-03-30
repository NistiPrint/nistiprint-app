-- Remove unicidade de numero_pedido no core de pedidos.
-- Motivo: Bling.numero é incremental e pode colidir entre contas/CNPJs.
-- A unicidade global deve ser garantida por pedidos.codigo_pedido_externo (ex: order_sn/numeroLoja).

ALTER TABLE IF EXISTS "public"."pedidos"
  DROP CONSTRAINT IF EXISTS "pedidos_numero_pedido_key";

