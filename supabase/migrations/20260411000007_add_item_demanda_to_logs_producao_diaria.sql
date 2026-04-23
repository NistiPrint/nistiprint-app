-- Adicionar colunas para rastreamento de demanda em logs de produção diária
-- Isso permite rastrear logs associados a demandas específicas
-- As colunas podem ser NULL quando não associadas a uma demanda (produção avulsa)

ALTER TABLE logs_producao_diaria
ADD COLUMN IF NOT EXISTS item_demanda_id INTEGER,
ADD COLUMN IF NOT EXISTS demanda_nome VARCHAR(255);

-- Criar índices para consultas de histórico
CREATE INDEX IF NOT EXISTS idx_logs_producao_diaria_item_demanda_id
ON logs_producao_diaria(item_demanda_id);

-- Comentário sobre as colunas
COMMENT ON COLUMN logs_producao_diaria.item_demanda_id IS 'ID do item de demanda associado (opcional - NULL para produção avulsa)';
COMMENT ON COLUMN logs_producao_diaria.demanda_nome IS 'Nome da demanda para rastreamento em logs (opcional - NULL para produção avulsa)';
