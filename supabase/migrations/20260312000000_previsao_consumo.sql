-- Migration para Previsão de Consumo de Demandas
CREATE TABLE IF NOT EXISTS public.previsao_consumo_demanda (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    demanda_id INTEGER NOT NULL REFERENCES public.demandas_producao(id) ON DELETE CASCADE,
    produto_id BIGINT NOT NULL REFERENCES public.produtos(id),
    quantidade_prevista NUMERIC(15,4) NOT NULL,
    unidade TEXT,
    status TEXT DEFAULT 'PLANEJADO', -- PLANEJADO, REALIZADO, CANCELADO
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_previsao_demanda_id ON public.previsao_consumo_demanda(demanda_id);
CREATE INDEX IF NOT EXISTS idx_previsao_produto_id ON public.previsao_consumo_demanda(produto_id);

-- View para consolidado de materiais necessários
CREATE OR REPLACE VIEW public.view_consolidado_previsao_materiais AS
SELECT 
    p.id AS produto_id,
    p.sku,
    p.nome AS produto_nome,
    p.unidade_medida_id,
    um.nome AS unidade_nome,
    SUM(pre.quantidade_prevista) AS total_necessario,
    COUNT(DISTINCT pre.demanda_id) AS num_demandas
FROM 
    public.previsao_consumo_demanda pre
JOIN 
    public.produtos p ON pre.produto_id = p.id
LEFT JOIN 
    public.unidades_medida um ON p.unidade_medida_id = um.id
JOIN 
    public.demandas_producao d ON pre.demanda_id = d.id
WHERE 
    d.status NOT IN ('CONCLUIDO', 'CANCELADO')
    AND pre.status = 'PLANEJADO'
GROUP BY 
    p.id, p.sku, p.nome, p.unidade_medida_id, um.nome;
