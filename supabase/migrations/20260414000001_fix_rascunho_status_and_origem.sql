-- Migration: Fix RASCUNHO status and origem_demanda
-- Objetivo: 
-- 1. Corrigir status RASCUNHO que foi convertido incorretamente para AGUARDANDO
-- 2. Corrigir origem_demanda para rascunhos criados automaticamente
-- Data: 2026-04-14

-- 1. Restaurar status RASCUNHO para demandas que são rascunhos
-- Identificamos rascunhos pela presença de campos específicos de rascunho
UPDATE demandas_producao 
SET status = 'RASCUNHO'
WHERE status = 'AGUARDANDO'
  AND (
    -- Campos que indicam ser um rascunho
    rascunho_expira_em IS NOT NULL
    OR editado_pelo_usuario IS NOT NULL
    OR editado_em IS NOT NULL
    OR pedidos_apos_edicao_qtd IS NOT NULL
    OR origem_demanda = 'AUTOMATICA'
    OR descricao ILIKE '%rascunho%'
  );

-- 2. Corrigir origem_demanda para rascunhos criados automaticamente
-- Rascunhos sem edição manual e com origem_demanda=NULL ou 'MANUAL' 
-- que foram criados pelo processo automático devem ser marcados como 'AUTOMATICA'
UPDATE demandas_producao 
SET origem_demanda = 'AUTOMATICA'
WHERE status = 'RASCUNHO'
  AND (origem_demanda IS NULL OR origem_demanda = 'MANUAL')
  AND editado_pelo_usuario = false
  AND (
    -- Indicadores de criação automática
    rascunho_expira_em IS NOT NULL
    OR created_at > '2026-04-01'::date  -- Apenas rascunhos recentes (após implementação)
  );

-- 3. Garantir que rascunhos editados manualmente tenham origem_demanda='MANUAL'
UPDATE demandas_producao 
SET origem_demanda = 'MANUAL'
WHERE status = 'RASCUNHO'
  AND editado_pelo_usuario = true
  AND (origem_demanda IS NULL OR origem_demanda = 'AUTOMATICA');

-- Verificação pós-migration
SELECT 
    status,
    origem_demanda,
    COUNT(*) as quantidade
FROM demandas_producao
WHERE status = 'RASCUNHO'
GROUP BY status, origem_demanda
ORDER BY quantidade DESC;
