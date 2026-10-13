-- O catálogo já possuía idx_demandas_item_origem_pedido cobrindo a FK.
-- Remove apenas o índice redundante criado pela migration anterior.
DROP INDEX IF EXISTS public.idx_demandas_item_origem_pedido_id;
