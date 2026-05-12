-- =============================================================
-- MIGRATION: Add marketplace modules
-- Date: 2026-05-12
-- Scope:
--   - Add Kwai, TikTok Shop, Loja Integrada and Amazon Fulfillment.
--   - Replace the old Amazon catalog entry with Amazon FBA Classic.
--   - Keep the migration idempotent for local/prod reruns.
-- =============================================================

ALTER TABLE public.integration_modules
    ADD COLUMN IF NOT EXISTS tipo varchar(50),
    ADD COLUMN IF NOT EXISTS slug varchar(100),
    ADD COLUMN IF NOT EXISTS is_aggregator boolean DEFAULT false;

ALTER TABLE public.installed_integrations
    ADD COLUMN IF NOT EXISTS platform_slug varchar(100);

CREATE UNIQUE INDEX IF NOT EXISTS idx_integration_modules_slug
    ON public.integration_modules(slug)
    WHERE slug IS NOT NULL;

-- Existing Amazon installs should now point at the replacement module.
UPDATE public.installed_integrations ii
   SET module_id = 'amazonfba_classic',
       updated_at = now()
 WHERE ii.module_id = 'amazon'
   AND NOT EXISTS (
       SELECT 1
         FROM public.installed_integrations target
        WHERE target.module_id = 'amazonfba_classic'
          AND target.instance_name = ii.instance_name
   );

UPDATE public.installed_integrations ii
   SET platform_slug = 'amazonfba_classic',
       updated_at = now()
 WHERE ii.module_id IN ('amazon', 'amazonfba_classic')
    OR ii.platform_slug = 'amazon';

-- Rename the catalog row when the target does not exist yet. If both rows
-- exist, the old Amazon row is deactivated below.
UPDATE public.integration_modules
   SET id = 'amazonfba_classic',
       slug = 'amazonfba_classic',
       name = 'Amazon FBA Classic',
       description = 'Integracao com Amazon FBA (Fulfillment by Amazon) para gerenciamento de pedidos e estoque fulfillment.',
       category = 'Marketplace',
       tipo = 'MARKETPLACE',
       is_active = true,
       updated_at = now()
 WHERE id = 'amazon'
   AND NOT EXISTS (
       SELECT 1
         FROM public.integration_modules
        WHERE id = 'amazonfba_classic'
   );

UPDATE public.integration_modules
   SET is_active = false,
       slug = CASE WHEN slug = 'amazon' THEN 'amazon_legacy' ELSE slug END,
       name = CASE WHEN name = 'Amazon' THEN 'Amazon (legacy)' ELSE name END,
       updated_at = now()
 WHERE id = 'amazon';

INSERT INTO public.integration_modules (
    id,
    slug,
    name,
    description,
    version,
    author,
    icon_url,
    category,
    tags,
    auth_flow,
    config_schema,
    auth_config,
    data_mapping_spec,
    tipo,
    is_aggregator,
    is_active,
    created_at,
    updated_at
)
VALUES
(
    'amazonfba_classic',
    'amazonfba_classic',
    'Amazon FBA Classic',
    'Integracao com Amazon FBA (Fulfillment by Amazon) para gerenciamento de pedidos e estoque fulfillment.',
    '1.0.0',
    'NistiPrint Team',
    'https://app.nistiprint.com.br/assets/img/amazon.svg',
    'Marketplace',
    ARRAY['amazon', 'fba', 'fulfillment', 'orders', 'inventory'],
    'oauth2',
    '{
        "title": "Configuracao Amazon FBA Classic",
        "type": "object",
        "required": ["seller_id", "mws_auth_token", "aws_access_key", "secret_key", "marketplace_id"],
        "properties": {
            "seller_id": {"type": "string", "title": "Seller ID"},
            "mws_auth_token": {"type": "string", "title": "MWS Auth Token"},
            "aws_access_key": {"type": "string", "title": "AWS Access Key"},
            "secret_key": {"type": "string", "title": "Secret Key"},
            "marketplace_id": {
                "type": "string",
                "title": "Marketplace ID",
                "description": "Amazon Marketplace ID (ex: A1AM78C64UM0Y8 para Brasil)",
                "default": "A1AM78C64UM0Y8"
            },
            "region": {
                "type": "string",
                "title": "Regiao",
                "enum": ["us-east-1", "eu-west-1", "ap-northeast-1"],
                "default": "us-east-1"
            }
        }
    }'::jsonb,
    '{
        "oauth_authorization_url": "https://sellercentral.amazon.com/apps/authorize/confirm",
        "oauth_token_url": "https://api.amazon.com/auth/o2/token",
        "scopes": ["selling_partner_api::notifications", "selling_partner_api::orders", "selling_partner_api::fba_inventory"]
    }'::jsonb,
    '{
        "test_endpoint": "/orders/v0/orders",
        "order_fields": {
            "order_id": "AmazonOrderId",
            "customer_name": "BuyerInfo.BuyerName",
            "shipping_address": "ShippingAddress",
            "order_date": "PurchaseDate",
            "status": "OrderStatus",
            "items": "OrderItems",
            "fulfillment_channel": "FulfillmentChannel"
        },
        "product_fields": {
            "sku": "SellerSKU",
            "name": "Title",
            "price": "ItemPrice.Amount",
            "quantity": "QuantityOrdered"
        }
    }'::jsonb,
    'MARKETPLACE',
    false,
    true,
    now(),
    now()
),
(
    'amazon_fulfillment',
    'amazon_fulfillment',
    'Amazon Fulfillment',
    'Integracao com Amazon Fulfillment Services para gerenciamento avancado de logistica e estoque.',
    '1.0.0',
    'NistiPrint Team',
    'https://app.nistiprint.com.br/assets/img/amazon.svg',
    'Marketplace',
    ARRAY['amazon', 'fulfillment', 'logistics', 'inventory', 'shipping'],
    'oauth2',
    '{
        "title": "Configuracao Amazon Fulfillment",
        "type": "object",
        "required": ["seller_id", "mws_auth_token", "aws_access_key", "secret_key", "marketplace_id"],
        "properties": {
            "seller_id": {"type": "string", "title": "Seller ID"},
            "mws_auth_token": {"type": "string", "title": "MWS Auth Token"},
            "aws_access_key": {"type": "string", "title": "AWS Access Key"},
            "secret_key": {"type": "string", "title": "Secret Key"},
            "marketplace_id": {"type": "string", "title": "Marketplace ID", "default": "A1AM78C64UM0Y8"},
            "region": {"type": "string", "title": "Regiao", "enum": ["us-east-1", "eu-west-1", "ap-northeast-1"], "default": "us-east-1"},
            "fulfillment_centers": {"type": "array", "title": "Centros de Fulfillment", "items": {"type": "string"}}
        }
    }'::jsonb,
    '{
        "oauth_authorization_url": "https://sellercentral.amazon.com/apps/authorize/confirm",
        "oauth_token_url": "https://api.amazon.com/auth/o2/token",
        "scopes": ["selling_partner_api::notifications", "selling_partner_api::orders", "selling_partner_api::fba_inventory", "selling_partner_api::fba_outbound"]
    }'::jsonb,
    '{
        "test_endpoint": "/fba/inventory/v1/summaries",
        "order_fields": {
            "order_id": "AmazonOrderId",
            "customer_name": "BuyerInfo.BuyerName",
            "shipping_address": "ShippingAddress",
            "order_date": "PurchaseDate",
            "status": "OrderStatus",
            "items": "OrderItems",
            "fulfillment_channel": "FulfillmentChannel"
        },
        "inventory_fields": {
            "sku": "sellerSku",
            "fn_sku": "fnSku",
            "total_quantity": "totalQuantity",
            "fulfillable_quantity": "fulfillableQuantity"
        }
    }'::jsonb,
    'MARKETPLACE',
    false,
    true,
    now(),
    now()
),
(
    'kwai',
    'kwai',
    'Kwai',
    'Integracao oficial com Kwai Shop para sincronizacao de pedidos e produtos.',
    '1.0.0',
    'NistiPrint Team',
    'https://app.nistiprint.com.br/assets/img/kwai.svg',
    'Marketplace',
    ARRAY['kwai', 'e-commerce', 'orders', 'inventory'],
    'oauth2',
    '{
        "title": "Configuracao Kwai Shop",
        "type": "object",
        "required": ["app_key", "app_secret"],
        "properties": {
            "app_key": {"type": "string", "title": "App Key"},
            "app_secret": {"type": "string", "title": "App Secret"},
            "region": {"type": "string", "title": "Regiao", "enum": ["BR", "US", "MX"], "default": "BR"}
        }
    }'::jsonb,
    '{
        "oauth_authorization_url": "https://open.kwaishope.com.br/oauth2/authorize",
        "oauth_token_url": "https://open.kwaishope.com.br/oauth2/token",
        "scopes": ["orders", "products", "shop_info"]
    }'::jsonb,
    '{
        "test_endpoint": "/api/v1/shop/info",
        "order_fields": {
            "order_id": "order_sn",
            "customer_name": "receiver_name",
            "shipping_address": "receiver_address",
            "order_date": "create_time",
            "status": "order_status",
            "items": "items"
        },
        "product_fields": {
            "sku": "sku",
            "name": "product_name",
            "price": "price",
            "quantity": "stock"
        }
    }'::jsonb,
    'MARKETPLACE',
    false,
    true,
    now(),
    now()
),
(
    'tiktokshop',
    'tiktokshop',
    'TikTok Shop',
    'Integracao oficial para conectar TikTok Shop a pedidos, produtos e estoque.',
    '1.0.0',
    'NistiPrint Team',
    'https://app.nistiprint.com.br/assets/img/tiktok.svg',
    'Marketplace',
    ARRAY['tiktok', 'tiktokshop', 'e-commerce', 'orders', 'inventory'],
    'oauth2',
    '{
        "title": "Configuracao TikTok Shop",
        "type": "object",
        "required": ["app_key", "app_secret"],
        "properties": {
            "app_key": {"type": "string", "title": "App Key"},
            "app_secret": {"type": "string", "title": "App Secret"},
            "shop_id": {"type": "string", "title": "Shop ID / Shop Cipher"}
        }
    }'::jsonb,
    '{
        "oauth_authorization_url": "https://auth.tiktok-shops.com/oauth/authorize",
        "oauth_token_url": "https://auth.tiktok-shops.com/api/v2/token/get"
    }'::jsonb,
    '{}'::jsonb,
    'MARKETPLACE',
    false,
    true,
    now(),
    now()
),
(
    'lojaintegrada',
    'lojaintegrada',
    'Loja Integrada',
    'Integracao via API Key com a Loja Integrada.',
    '1.0.0',
    'NistiPrint Team',
    'https://app.nistiprint.com.br/assets/img/lojaintegrada.svg',
    'Marketplace',
    ARRAY['lojaintegrada', 'e-commerce', 'orders', 'inventory'],
    'api_key',
    '{
        "title": "Configuracao Loja Integrada",
        "type": "object",
        "required": ["api_key", "app_key"],
        "properties": {
            "api_key": {"type": "string", "title": "Chave da API"},
            "app_key": {"type": "string", "title": "Chave do Aplicativo"}
        }
    }'::jsonb,
    '{}'::jsonb,
    '{}'::jsonb,
    'MARKETPLACE',
    false,
    true,
    now(),
    now()
),
(
    'magazineluiza',
    'magazineluiza',
    'Magazine Luiza',
    'Integracao com Magazine Luiza para vinculacao de lojas Bling, pedidos e canais de venda.',
    '1.0.0',
    'NistiPrint Team',
    'https://app.nistiprint.com.br/assets/img/magazineluiza.svg',
    'Marketplace',
    ARRAY['magazineluiza', 'magalu', 'e-commerce', 'orders', 'inventory'],
    'api_key',
    '{
        "title": "Configuracao Magazine Luiza",
        "type": "object",
        "required": ["api_key"],
        "properties": {
            "api_key": {"type": "string", "title": "Chave da API"},
            "seller_id": {"type": "string", "title": "Seller ID"}
        }
    }'::jsonb,
    '{}'::jsonb,
    '{"test_endpoint": "/orders"}'::jsonb,
    'MARKETPLACE',
    false,
    true,
    now(),
    now()
)
ON CONFLICT (id) DO UPDATE SET
    slug = EXCLUDED.slug,
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    version = EXCLUDED.version,
    author = EXCLUDED.author,
    icon_url = EXCLUDED.icon_url,
    category = EXCLUDED.category,
    tags = EXCLUDED.tags,
    auth_flow = EXCLUDED.auth_flow,
    config_schema = EXCLUDED.config_schema,
    auth_config = EXCLUDED.auth_config,
    data_mapping_spec = EXCLUDED.data_mapping_spec,
    tipo = EXCLUDED.tipo,
    is_aggregator = EXCLUDED.is_aggregator,
    is_active = EXCLUDED.is_active,
    updated_at = now();

GRANT SELECT ON TABLE public.integration_modules TO anon, authenticated, service_role;
