-- Adicionar colunas para rastreamento de produto e demanda (opcionais)
-- Isso permite agrupar histórico de movimentações por "produto X da demanda Y"
-- As colunas podem ser NULL quando não associadas a uma demanda (produção avulsa)

ALTER TABLE movimentacoes_estoque
ADD COLUMN IF NOT EXISTS produto_nome VARCHAR(255),
ADD COLUMN IF NOT EXISTS demanda_nome VARCHAR(255);

-- Criar índices para consultas de histórico
CREATE INDEX IF NOT EXISTS idx_movimentacoes_produto_demanda
ON movimentacoes_estoque(produto_nome, demanda_nome);

-- Comentário sobre as colunas
COMMENT ON COLUMN movimentacoes_estoque.produto_nome IS 'Nome do produto para rastreamento em logs (pode ser NULL para produção avulsa)';
COMMENT ON COLUMN movimentacoes_estoque.demanda_nome IS 'Nome da demanda para rastreamento em logs (pode ser NULL para produção avulsa)';
