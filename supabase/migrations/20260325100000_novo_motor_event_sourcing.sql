-- Migration: 20260325100000_novo_motor_event_sourcing.sql
-- Propósito: Recriação da estrutura orientada a eventos para desacoplamento do estoque
-- Desativa processamento em tempo real no dashboard

-- 1. Nova tabela de Eventos de Produção (Fonte da Verdade)
CREATE TABLE IF NOT EXISTS public.eventos_producao_v2 (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_demanda_id INTEGER REFERENCES public.itens_demanda(id) ON DELETE CASCADE,
    demanda_id INTEGER REFERENCES public.demandas_producao(id) ON DELETE CASCADE,
    estagio VARCHAR(50) NOT NULL, -- e.g., 'finalizado', 'retirada_miolo'
    quantidade_reportada NUMERIC(15,4) NOT NULL,
    tipo_evento VARCHAR(20) NOT NULL, -- 'SINAL' ou 'LIQUIDACAO'
    processado BOOLEAN NOT NULL DEFAULT false,
    correlation_id UUID DEFAULT gen_random_uuid(),
    usuario_id INTEGER REFERENCES public.usuarios(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Tabela de Saldo Consolidado (Cache de leitura do estado atual)
CREATE TABLE IF NOT EXISTS public.estoque_consolidado (
    produto_id INTEGER PRIMARY KEY REFERENCES public.produtos(id),
    saldo_total NUMERIC(15,4) NOT NULL DEFAULT 0,
    reservado NUMERIC(15,4) NOT NULL DEFAULT 0,
    ultimo_processamento_evento_id UUID REFERENCES public.eventos_producao_v2(id),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Índices para performance do novo motor
CREATE INDEX IF NOT EXISTS idx_eventos_v2_processado ON public.eventos_producao_v2(processado) WHERE processado = false;
CREATE INDEX IF NOT EXISTS idx_eventos_v2_item ON public.eventos_producao_v2(item_demanda_id);

-- Comentários
COMMENT ON TABLE public.eventos_producao_v2 IS 'Fonte da verdade: eventos imutáveis de produção.';
COMMENT ON TABLE public.estoque_consolidado IS 'Cache de leitura: estado atual calculado pelo motor.';
