-- Migration: Tabela consolidacoes_pedido para processamento assíncrono
-- Created: 2026-03-19

-- Tabela para armazenar consolidações de pedidos em processamento
CREATE TABLE IF NOT EXISTS public.consolidacoes_pedido (
    id BIGSERIAL PRIMARY KEY,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDENTE', -- PENDENTE, PROCESSANDO, PRONTO, ERRO
    platform VARCHAR(100) NOT NULL,
    channel_id BIGINT NOT NULL,
    channel_slug VARCHAR(100),
    file_path VARCHAR(500),
    file_name VARCHAR(255),
    period_filter_start TIMESTAMP WITH TIME ZONE,
    period_filter_end TIMESTAMP WITH TIME ZONE,
    options JSONB DEFAULT '{}',
    result_data JSONB,
    error_message TEXT,
    processing_started_at TIMESTAMP WITH TIME ZONE,
    processing_completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Foreign keys
    CONSTRAINT fk_consolidacoes_channel FOREIGN KEY (channel_id) REFERENCES public.canais_venda(id)
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_consolidacoes_status ON public.consolidacoes_pedido(status);
CREATE INDEX IF NOT EXISTS idx_consolidacoes_created_at ON public.consolidacoes_pedido(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_consolidacoes_platform ON public.consolidacoes_pedido(platform);
CREATE INDEX IF NOT EXISTS idx_consolidacoes_channel ON public.consolidacoes_pedido(channel_id);

-- Trigger para atualizar updated_at
CREATE OR REPLACE FUNCTION public.update_consolidacoes_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_consolidacoes_updated_at ON public.consolidacoes_pedido;
CREATE TRIGGER trigger_update_consolidacoes_updated_at
    BEFORE UPDATE ON public.consolidacoes_pedido
    FOR EACH ROW
    EXECUTE FUNCTION public.update_consolidacoes_updated_at();

-- RLS (Row Level Security) - se necessário
ALTER TABLE public.consolidacoes_pedido ENABLE ROW LEVEL SECURITY;

-- Policy para leitura (ajustar conforme necessidade)
DROP POLICY IF EXISTS "Usuários autenticados podem ver consolidacoes" ON public.consolidacoes_pedido;
CREATE POLICY "Usuários autenticados podem ver consolidacoes"
    ON public.consolidacoes_pedido
    FOR SELECT
    TO authenticated
    USING (true);

-- Policy para inserção
DROP POLICY IF EXISTS "Usuários autenticados podem criar consolidacoes" ON public.consolidacoes_pedido;
CREATE POLICY "Usuários autenticados podem criar consolidacoes"
    ON public.consolidacoes_pedido
    FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Policy para atualização
DROP POLICY IF EXISTS "Usuários autenticados podem atualizar consolidacoes" ON public.consolidacoes_pedido;
CREATE POLICY "Usuários autenticados podem atualizar consolidacoes"
    ON public.consolidacoes_pedido
    FOR UPDATE
    TO authenticated
    USING (true);

-- Comment na tabela
COMMENT ON TABLE public.consolidacoes_pedido IS 'Armazena consolidações de pedidos em processamento assíncrono';
COMMENT ON COLUMN public.consolidacoes_pedido.status IS 'Status: PENDENTE, PROCESSANDO, PRONTO, ERRO';
COMMENT ON COLUMN public.consolidacoes_pedido.result_data IS 'Dados consolidados em formato JSON (capas, miolos, pedidos, etc.)';
COMMENT ON COLUMN public.consolidacoes_pedido.options IS 'Opções de processamento: print_orders, is_flex, mode, etc.';
