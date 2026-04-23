-- Migration: Normalizar status da tabela demandas_producao
-- Objetivo: Padronizar todos os status para Upper Snake Case
-- Data: 2026-03-28

-- 1. Normalizar status legados para o novo padrão
UPDATE demandas_producao 
SET status = CASE
    -- Já estão no formato correto
    WHEN status IN ('AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'COLETADO', 'CONCLUIDO', 'CANCELADO', 'PENDENTE') 
        THEN status
    
    -- Em Produção / Em Andamento → EM_PRODUCAO
    WHEN status IN ('Em Produção', 'Em Andamento', 'EM PRODUCAO', 'em_producao', 'Em producao') 
        THEN 'EM_PRODUCAO'
    
    -- Aguardando / Pendente / Rascunho → AGUARDANDO
    WHEN status IN ('Pendente', 'Rascunho', 'Criada', 'AGUARDANDO COLETA', 'Aguardando') 
        THEN 'AGUARDANDO'
    
    -- Coleta Parcial → COLETA_PARCIAL
    WHEN status IN ('Coleta Parcial', 'COLETA PARCIAL', 'Coleta parcial') 
        THEN 'COLETA_PARCIAL'
    
    -- Coletado → COLETADO
    WHEN status IN ('Coletado', 'COLETADO', 'Coletado/') 
        THEN 'COLETADO'
    
    -- Finalizado / Concluído → CONCLUIDO
    WHEN status IN ('Finalizado', 'Concluído', 'CONCLUIDO/', 'Finalizado/', 'concluido') 
        THEN 'CONCLUIDO'
    
    -- Cancelado → CANCELADO
    WHEN status IN ('Cancelado', 'CANCELADO', 'cancelado') 
        THEN 'CANCELADO'
    
    -- Em Produção (português com acento) → EM_PRODUCAO
    WHEN status LIKE 'Em Produ%C3%A7%C3%A3o' OR status LIKE 'Em Produçã%' 
        THEN 'EM_PRODUCAO'
    
    -- Default: converter para UPPER_SNAKE_CASE
    ELSE UPPER(REPLACE(status, ' ', '_'))
END
WHERE status IS NOT NULL 
  AND status NOT IN ('AGUARDANDO', 'EM_PRODUCAO', 'COLETA_PARCIAL', 'COLETADO', 'CONCLUIDO', 'CANCELADO', 'PENDENTE');

-- 2. Garantir que status NULL seja AGUARDANDO
UPDATE demandas_producao 
SET status = 'AGUARDANDO'
WHERE status IS NULL;

-- 3. Criar índice para performance nas consultas por status
CREATE INDEX IF NOT EXISTS idx_demandas_producao_status_normalizado 
ON demandas_producao(status);

-- 4. Adicionar constraint CHECK para validar status futuros
-- Nota: Isso pode falhar se houver dados inválidos, então usamos IF NOT EXISTS
ALTER TABLE demandas_producao 
DROP CONSTRAINT IF EXISTS check_status_valido;

-- 5. Opcional: Adicionar comentário na coluna
COMMENT ON COLUMN demandas_producao.status IS 'Status da demanda: AGUARDANDO, EM_PRODUCAO, COLETA_PARCIAL, COLETADO, CONCLUIDO, CANCELADO';

-- 6. Log de auditoria (opcional - removido pois tabela pode não existir)
-- INSERT INTO auditoria_estoque (...) VALUES (...);

-- Verificação pós-migration
SELECT 
    status, 
    COUNT(*) as quantidade
FROM demandas_producao
GROUP BY status
ORDER BY quantidade DESC;
