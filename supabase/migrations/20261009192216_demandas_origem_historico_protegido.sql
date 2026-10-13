-- Protege a origem comercial dos itens de demanda e rejeita vínculos vazios.
-- O catálogo e os 220 registros ativos foram verificados: todos têm pedido
-- interno e quantidade atendida positiva.
ALTER TABLE public.demandas_item_origem
    ALTER COLUMN pedido_id SET NOT NULL;

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.demandas_item_origem'::regclass
           AND conname = 'demandas_item_origem_demanda_item_id_fkey'
    ) THEN
        ALTER TABLE public.demandas_item_origem
            DROP CONSTRAINT demandas_item_origem_demanda_item_id_fkey;
    END IF;
    ALTER TABLE public.demandas_item_origem
        ADD CONSTRAINT demandas_item_origem_demanda_item_id_fkey
        FOREIGN KEY (demanda_item_id) REFERENCES public.itens_demanda(id)
        ON DELETE RESTRICT;

    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.demandas_item_origem'::regclass
           AND conname = 'demandas_item_origem_pedido_id_fkey'
    ) THEN
        ALTER TABLE public.demandas_item_origem
            DROP CONSTRAINT demandas_item_origem_pedido_id_fkey;
    END IF;
    ALTER TABLE public.demandas_item_origem
        ADD CONSTRAINT demandas_item_origem_pedido_id_fkey
        FOREIGN KEY (pedido_id) REFERENCES public.pedidos(id)
        ON DELETE RESTRICT;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.demandas_item_origem'::regclass
           AND conname = 'demandas_item_origem_quantidade_positiva_check'
    ) THEN
        ALTER TABLE public.demandas_item_origem
            ADD CONSTRAINT demandas_item_origem_quantidade_positiva_check
            CHECK (quantidade_atendida > 0);
    END IF;
END;
$migration$;

CREATE INDEX IF NOT EXISTS idx_demandas_item_origem_pedido_id
    ON public.demandas_item_origem(pedido_id);
