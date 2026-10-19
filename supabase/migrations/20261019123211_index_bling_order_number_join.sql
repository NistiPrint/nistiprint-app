-- Personalized order views join canonical orders to Bling by numero_pedido.
CREATE INDEX IF NOT EXISTS idx_pedidos_bling_numero_pedido
    ON public.pedidos_bling (numero_pedido);
