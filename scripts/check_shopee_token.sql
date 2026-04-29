-- =====================================================
-- VERIFICAÇÃO E CORREÇÃO: Access Token Shopee
-- =====================================================
-- O access_token está em credentials, não em config
-- =====================================================

-- 1. Verificar integração específica (ID 6)
SELECT 
    id,
    module_id,
    instance_name,
    is_active,
    config->>'shop_id' as shop_id,
    config->>'partner_id' as partner_id,
    CASE WHEN config->>'partner_key' IS NOT NULL THEN 'PRESENT' ELSE 'MISSING' END as partner_key_status,
    CASE WHEN credentials->>'access_token' IS NOT NULL THEN 'PRESENT' ELSE 'MISSING' END as access_token_status,
    credentials->>'expires_in' as expires_in,
    credentials->>'refresh_token' as refresh_token_preview
FROM installed_integrations
WHERE id = 6;

-- 2. Verificar TODAS as integrações Shopee
SELECT 
    id,
    instance_name,
    is_active,
    config->>'shop_id' as shop_id,
    CASE WHEN credentials->>'access_token' IS NOT NULL THEN '✓' ELSE '✗' END as has_token,
    created_at,
    updated_at
FROM installed_integrations
WHERE module_id = 'shopee'
ORDER BY updated_at DESC;

-- 3. Verificar se há access_token mas está vazio
SELECT 
    id,
    instance_name,
    credentials->>'access_token' as access_token,
    LENGTH(credentials->>'access_token') as token_length
FROM installed_integrations
WHERE module_id = 'shopee';

-- =====================================================
-- SOLUÇÃO 1: Re-autorizar via UI (Recomendado)
-- =====================================================
-- Acessar /admin/integracoes → Shopee → Re-autorizar
-- Isso irá atualizar o access_token automaticamente

-- =====================================================
-- SOLUÇÃO 2: Atualizar manualmente (se tiver o token)
-- =====================================================
-- Substituir <NOVO_ACCESS_TOKEN> pelo token obtido via OAuth

-- UPDATE installed_integrations
-- SET 
--     credentials = credentials || '{"access_token": "<NOVO_ACCESS_TOKEN>"}'::jsonb,
--     updated_at = NOW()
-- WHERE id = 6;

-- =====================================================
-- SOLUÇÃO 3: Verificar se token expirou
-- =====================================================
-- Shopee access_tokens expiram após 24 horas (86400 segundos)
-- Se expires_in estiver presente e for antigo, precisa renovar

SELECT 
    id,
    instance_name,
    credentials->>'expires_in' as expires_in_seconds,
    credentials->>'access_token' as token_preview,
    updated_at,
    updated_at + (credentials->>'expires_in')::interval * interval '1 second' as token_expires_at,
    CASE 
        WHEN updated_at + (credentials->>'expires_in')::interval * interval '1 second' < NOW() 
        THEN 'EXPIRED'
        ELSE 'VALID'
    END as token_status
FROM installed_integrations
WHERE module_id = 'shopee';

-- =====================================================
-- DEBUG: Verificar estrutura completa do JSON
-- =====================================================
SELECT 
    id,
    jsonb_typeof(config) as config_type,
    jsonb_typeof(credentials) as credentials_type,
    config,
    credentials
FROM installed_integrations
WHERE id = 6;
