-- ============================================
-- Script de Correção de Vínculos de Integração
-- ============================================
-- Este script corrige os vínculos em integracao_canais_config para garantir
-- que bling_integration_id e marketplace_integration_id apontem para as
-- integrações corretas baseadas no module_id.
--
-- Uso: Executar após deploy das mudanças no código
-- ============================================

BEGIN;

-- 1. Diagnóstico: Mostrar vínculos atuais
SELECT 
    icc.id,
    icc.canal_venda_id,
    cv.nome as canal_nome,
    icc.bling_loja_id,
    icc.integration_id as legacy_integration_id,
    icc.bling_integration_id,
    ii_bling.module_id as bling_module_id,
    icc.marketplace_integration_id,
    ii_mp.module_id as marketplace_module_id,
    icc.plataforma_nome
FROM integracao_canais_config icc
LEFT JOIN canais_venda cv ON cv.id = icc.canal_venda_id
LEFT JOIN installed_integrations ii_bling ON ii_bling.id = icc.bling_integration_id
LEFT JOIN installed_integrations ii_mp ON ii_mp.id = icc.marketplace_integration_id
WHERE icc.is_active = true
ORDER BY icc.canal_venda_id;

-- 2. Correção: Atualizar bling_integration_id onde integration_id aponta para Bling
-- (caso bling_integration_id esteja NULL mas integration_id seja uma integração Bling)
UPDATE integracao_canais_config icc
SET bling_integration_id = ii.id
FROM installed_integrations ii
WHERE icc.integration_id = ii.id
  AND ii.module_id = 'bling'
  AND icc.bling_integration_id IS NULL;

-- 3. Correção: Atualizar marketplace_integration_id onde integration_id aponta para marketplace
-- (caso marketplace_integration_id esteja NULL mas integration_id seja uma integração não-Bling)
UPDATE integracao_canais_config icc
SET marketplace_integration_id = ii.id
FROM installed_integrations ii
WHERE icc.integration_id = ii.id
  AND ii.module_id != 'bling'
  AND icc.marketplace_integration_id IS NULL;

-- 4. Correção específica: Garantir que vínculos Shopee apontem para integração Shopee
-- Atualiza marketplace_integration_id para a integração Shopee ativa com shop_id configurado
UPDATE integracao_canais_config icc
SET marketplace_integration_id = ii.id
FROM installed_integrations ii
WHERE icc.plataforma_nome = 'shopee'
  AND ii.module_id = 'shopee'
  AND ii.is_active = true
  AND (ii.config->>'shop_id') IS NOT NULL
  AND (icc.marketplace_integration_id IS NULL 
       OR icc.marketplace_integration_id != ii.id
       OR EXISTS (
           SELECT 1 FROM installed_integrations ii_old 
           WHERE ii_old.id = icc.marketplace_integration_id 
           AND ii_old.module_id != 'shopee'
       ));

-- 5. Diagnóstico pós-correção: Mostrar vínculos atualizados
SELECT 
    icc.id,
    icc.canal_venda_id,
    cv.nome as canal_nome,
    icc.bling_loja_id,
    icc.bling_integration_id,
    ii_bling.module_id as bling_module_id,
    ii_bling.instance_name as bling_instance,
    icc.marketplace_integration_id,
    ii_mp.module_id as marketplace_module_id,
    ii_mp.instance_name as marketplace_instance,
    icc.plataforma_nome,
    CASE 
        WHEN ii_bling.module_id = 'bling' AND ii_mp.module_id IN ('shopee', 'amazon', 'mercadolivre', 'shein', 'tiktok') 
        THEN '✓ OK'
        WHEN ii_bling.module_id IS NULL THEN '⚠ bling_integration_id NULL'
        WHEN ii_mp.module_id IS NULL THEN '⚠ marketplace_integration_id NULL'
        WHEN ii_bling.module_id != 'bling' THEN '✗ bling_integration_id com módulo errado'
        WHEN ii_mp.module_id NOT IN ('shopee', 'amazon', 'mercadolivre', 'shein', 'tiktok') THEN '✗ marketplace_integration_id com módulo errado'
        ELSE '?'
    END as status
FROM integracao_canais_config icc
LEFT JOIN canais_venda cv ON cv.id = icc.canal_venda_id
LEFT JOIN installed_integrations ii_bling ON ii_bling.id = icc.bling_integration_id
LEFT JOIN installed_integrations ii_mp ON ii_mp.id = icc.marketplace_integration_id
WHERE icc.is_active = true
ORDER BY icc.canal_venda_id;

-- 6. Log de alterações (opcional - remover em produção se não houver tabela de log)
-- INSERT INTO integration_refresh_logs (integration_id, status, message, created_at)
-- SELECT 
--     marketplace_integration_id,
--     'info',
--     'Vínculo corrigido via script de migração',
--     NOW()
-- FROM integracao_canais_config
-- WHERE updated_at >= NOW() - INTERVAL '1 minute';

COMMIT;
