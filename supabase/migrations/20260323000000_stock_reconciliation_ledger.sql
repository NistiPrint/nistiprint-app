-- Migration: stock_reconciliation_ledger
-- Data: 2026-03-23
-- Propósito: Tabela ledger para rastrear o processamento efetivo de estoque por item/estágio

-- Criar função update_modified_column se não existir
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Usamos INTEGER para manter consistência com o schema legado (itens_demanda.id e demandas_producao.id são serial/int)
CREATE TABLE IF NOT EXISTS public.demanda_estoque_processado (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id INTEGER NOT NULL REFERENCES public.itens_demanda(id),
    demanda_id INTEGER NOT NULL REFERENCES public.demandas_producao(id),
    estagio VARCHAR(50) NOT NULL, -- ex: 'capas_impressas_qtd', 'finalizados_qtd'
    quantidade DECIMAL(10,2) NOT NULL, -- Quantidade processada nesta transação (pode ser negativa em estornos)
    saldo_acumulado DECIMAL(10,2) NOT NULL, -- Saldo acumulado processado até o momento para este estágio/item
    correlation_id VARCHAR(100), -- Para rastrear qual transação gerou isso
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index para busca rápida por item e estágio (essencial para o cálculo de delta)
CREATE INDEX IF NOT EXISTS idx_estoque_proc_item_estagio ON public.demanda_estoque_processado(item_id, estagio);
CREATE INDEX IF NOT EXISTS idx_estoque_proc_demanda ON public.demanda_estoque_processado(demanda_id);

-- Trigger para updated_at
DROP TRIGGER IF EXISTS update_demanda_estoque_processado_modtime ON public.demanda_estoque_processado;
CREATE TRIGGER update_demanda_estoque_processado_modtime
    BEFORE UPDATE ON public.demanda_estoque_processado
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_column();

-- Grant permissions
GRANT ALL ON public.demanda_estoque_processado TO postgres;
GRANT ALL ON public.demanda_estoque_processado TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.demanda_estoque_processado TO authenticated;
