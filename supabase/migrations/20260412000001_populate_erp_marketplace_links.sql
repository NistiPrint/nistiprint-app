-- Migração para popular erp_marketplace_links com base em channel_connections
-- Esta migração cria vínculos entre instâncias ERP Bling e instâncias de Marketplace

-- Tornar marketplace_integration_id nullable para marketplaces não instalados ainda
ALTER TABLE erp_marketplace_links ALTER COLUMN marketplace_integration_id DROP NOT NULL;

-- Primeiro, vamos identificar qual marketplace está associado a cada canal
-- com base no canal_id e na plataforma correspondente

-- Mapeamento de canais para marketplaces (baseado em canais_venda):
-- canal_id=1 (Shopee) -> marketplace Shopee (installed_integrations.id=6)
-- canal_id=7 (Shein) -> marketplace Shein (não instalado ainda)
-- canal_id=8 (Amazon) -> marketplace Amazon (não instalado ainda)
-- canal_id=9 (Mercado Livre) -> marketplace ML (não instalado ainda)

-- Inserir vínculos para Shopee (única marketplace instalada)
INSERT INTO erp_marketplace_links (erp_integration_id, marketplace_integration_id, erp_store_id, store_name, config, created_at, updated_at)
SELECT 
    cc.integration_id as erp_integration_id,
    6 as marketplace_integration_id, -- Shopee integration ID
    cc.aggregator_store_id as erp_store_id,
    cc.aggregator_store_name as store_name,
    cc.config,
    NOW() as created_at,
    NOW() as updated_at
FROM channel_connections cc
WHERE cc.channel_id = 1 -- Shopee
  AND cc.is_active = true
ON CONFLICT (erp_integration_id, erp_store_id) DO NOTHING;

-- Inserir vínculos para outros marketplaces (sem marketplace_integration_id por enquanto)
-- Isso permite que o sistema funcione mesmo sem as integrações de marketplace instaladas

-- Shein
INSERT INTO erp_marketplace_links (erp_integration_id, marketplace_integration_id, erp_store_id, store_name, config, created_at, updated_at)
SELECT 
    cc.integration_id as erp_integration_id,
    NULL as marketplace_integration_id, -- Shein não instalado ainda
    cc.aggregator_store_id as erp_store_id,
    cc.aggregator_store_name as store_name,
    cc.config,
    NOW() as created_at,
    NOW() as updated_at
FROM channel_connections cc
WHERE cc.channel_id = 7 -- Shein
  AND cc.is_active = true
ON CONFLICT (erp_integration_id, erp_store_id) DO NOTHING;

-- Amazon
INSERT INTO erp_marketplace_links (erp_integration_id, marketplace_integration_id, erp_store_id, store_name, config, created_at, updated_at)
SELECT 
    cc.integration_id as erp_integration_id,
    NULL as marketplace_integration_id, -- Amazon não instalado ainda
    cc.aggregator_store_id as erp_store_id,
    cc.aggregator_store_name as store_name,
    cc.config,
    NOW() as created_at,
    NOW() as updated_at
FROM channel_connections cc
WHERE cc.channel_id = 8 -- Amazon
  AND cc.is_active = true
ON CONFLICT (erp_integration_id, erp_store_id) DO NOTHING;

-- Mercado Livre
INSERT INTO erp_marketplace_links (erp_integration_id, marketplace_integration_id, erp_store_id, store_name, config, created_at, updated_at)
SELECT 
    cc.integration_id as erp_integration_id,
    NULL as marketplace_integration_id, -- ML não instalado ainda
    cc.aggregator_store_id as erp_store_id,
    cc.aggregator_store_name as store_name,
    cc.config,
    NOW() as created_at,
    NOW() as updated_at
FROM channel_connections cc
WHERE cc.channel_id = 9 -- Mercado Livre
  AND cc.is_active = true
ON CONFLICT (erp_integration_id, erp_store_id) DO NOTHING;

-- Adicionar comentário explicando a estrutura
COMMENT ON TABLE erp_marketplace_links IS 'Vínculo entre instância ERP (Bling) e instâncias de Marketplace. Permite que o sistema saiba qual instância de ERP Bling é associada a qual instância de integração com Marketplace.';
