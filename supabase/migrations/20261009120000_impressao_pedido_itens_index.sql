-- A impressão carrega todos os itens de uma lista de pedidos.
-- A FK não cria índice automaticamente e o índice parcial de personalizados
-- não atende os pedidos sem personalização.
CREATE INDEX IF NOT EXISTS idx_itens_pedido_pedido_id
    ON public.itens_pedido (pedido_id);
