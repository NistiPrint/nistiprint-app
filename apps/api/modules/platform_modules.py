"""
Module definitions for supported platforms in the integration marketplace
"""
from nistiprint_shared.models.integration_module import IntegrationModule


def get_shopee_module_definition():
    """Get the module definition for Shopee integration"""
    return IntegrationModule(
        id="shopee",
        name="Shopee Integration",
        description="Official integration for connecting Shopee marketplace to your inventory and order management system.",
        version="1.0.0",
        author="NistiPrint Team",
        icon_url="https://app.nistiprint.com.br/assets/img/shopee.svg",
        category="Marketplace",
        tags=["shopee", "e-commerce", "orders", "inventory"],
        auth_flow="oauth2",
        config_schema={
            "title": "Shopee Configuration",
            "type": "object",
            "required": ["shop_id", "partner_id", "partner_key"],
            "properties": {
                "shop_id": {
                    "type": "string",
                    "title": "Shop ID",
                    "description": "Your Shopee Shop ID"
                },
                "partner_id": {
                    "type": "string",
                    "title": "Partner ID",
                    "description": "Your Shopee Partner ID"
                },
                "partner_key": {
                    "type": "string",
                    "title": "Partner Key",
                    "description": "Your Shopee Partner Key"
                },
                "region": {
                    "type": "string",
                    "title": "Region",
                    "enum": ["tw", "th", "sg", "my", "vn", "ph", "id", "br", "mx", "co", "cl", "pl", "es"],
                    "default": "br"
                }
            }
        },
        auth_config={
            "oauth_authorization_url": "https://partner.shopeemobile.com/api/v2/shop/auth_partner",
            "oauth_token_url": "https://partner.shopeemobile.com/api/v2/auth/token/get",
            "scopes": ["shop_info", "item", "order", "logistics"]
        },
        data_mapping_spec={
            "test_endpoint": "/api/v2/shop/get_profile",
            "order_fields": {
                "order_id": "ordersn",
                "customer_name": "recipient_address.name",
                "shipping_address": "recipient_address.full_address",
                "order_date": "create_time",
                "status": "order_status",
                "items": "order_line_items"
            },
            "product_fields": {
                "sku": "model.sku",
                "name": "item_name",
                "price": "model.original_price",
                "quantity": "model.stock"
            }
        }
    )


def get_amazon_module_definition():
    """Get the module definition for Amazon integration"""
    return IntegrationModule(
        id="amazon",
        name="Amazon Integration",
        description="Official integration for connecting Amazon marketplace to your inventory and order management system.",
        version="1.0.0",
        author="NistiPrint Team",
        icon_url="https://app.nistiprint.com.br/assets/img/amazon.svg",
        category="Marketplace",
        tags=["amazon", "e-commerce", "orders", "inventory"],
        auth_flow="oauth2",
        config_schema={
            "title": "Amazon Configuration",
            "type": "object",
            "required": ["seller_id", "mws_auth_token", "aws_access_key", "secret_key", "marketplace_id"],
            "properties": {
                "seller_id": {
                    "type": "string",
                    "title": "Seller ID",
                    "description": "Your Amazon Seller ID"
                },
                "mws_auth_token": {
                    "type": "string",
                    "title": "MWS Auth Token",
                    "description": "Your Amazon MWS Authorization Token"
                },
                "aws_access_key": {
                    "type": "string",
                    "title": "AWS Access Key",
                    "description": "Your AWS Access Key ID"
                },
                "secret_key": {
                    "type": "string",
                    "title": "Secret Key",
                    "description": "Your AWS Secret Access Key"
                },
                "marketplace_id": {
                    "type": "string",
                    "title": "Marketplace ID",
                    "description": "Amazon Marketplace ID (e.g., A1AM78C64UM0Y8 for Brazil)"
                }
            }
        },
        auth_config={
            "oauth_authorization_url": "https://sellercentral.amazon.com/apps/authorize/confirm",
            "oauth_token_url": "https://api.amazon.com/auth/o2/token",
            "scopes": ["selling_partner_api::notifications", "selling_partner_api::orders"]
        },
        data_mapping_spec={
            "order_fields": {
                "order_id": "AmazonOrderId",
                "customer_name": "BuyerName",
                "shipping_address": "ShippingAddress",
                "order_date": "PurchaseDate",
                "status": "OrderStatus",
                "items": "OrderItems"
            },
            "product_fields": {
                "sku": "SellerSKU",
                "name": "ItemName",
                "price": "Price",
                "quantity": "Quantity"
            }
        }
    )


def get_mercado_livre_module_definition():
    """Get the module definition for Mercado Livre integration"""
    return IntegrationModule(
        id="mercadolivre",
        name="Mercado Livre Integration",
        description="Official integration for connecting Mercado Livre marketplace to your inventory and order management system.",
        version="1.0.0",
        author="NistiPrint Team",
        icon_url="https://app.nistiprint.com.br/assets/img/mercadolivre.svg",
        category="Marketplace",
        tags=["mercadolivre", "e-commerce", "orders", "inventory"],
        auth_flow="oauth2",
        config_schema={
            "title": "Mercado Livre Configuration",
            "type": "object",
            "required": ["client_id", "client_secret"],
            "properties": {
                "client_id": {
                    "type": "string",
                    "title": "Client ID",
                    "description": "Your Mercado Livre Application Client ID"
                },
                "client_secret": {
                    "type": "string",
                    "title": "Client Secret",
                    "description": "Your Mercado Livre Application Client Secret"
                },
                "redirect_uri": {
                    "type": "string",
                    "title": "Redirect URI",
                    "description": "Redirect URI for OAuth callback",
                    "default": "https://yoursite.com/callback/ml"
                }
            }
        },
        auth_config={
            "oauth_authorization_url": "https://auth.mercadolibre.com.br/authorization",
            "oauth_token_url": "https://api.mercadolibre.com/oauth/token",
        },
        data_mapping_spec={
            "test_endpoint": "/users/me",
            "order_fields": {
                "order_id": "id",
                "customer_name": "buyer.nickname",
                "shipping_address": "shipping.receiver_address",
                "order_date": "date_created",
                "status": "status",
                "items": "order_items"
            },
            "product_fields": {
                "sku": "seller_custom_field",
                "name": "title",
                "price": "price",
                "quantity": "available_quantity"
            }
        }
    )


def get_shein_module_definition():
    """Get the module definition for Shein integration"""
    return IntegrationModule(
        id="shein",
        name="Shein Integration",
        description="Official integration for connecting Shein marketplace to your inventory and order management system.",
        version="1.0.0",
        author="NistiPrint Team",
        icon_url="https://app.nistiprint.com.br/assets/img/shein.svg",
        category="Marketplace",
        tags=["shein", "e-commerce", "orders", "inventory"],
        auth_flow="api_key",
        config_schema={
            "title": "Shein Configuration",
            "type": "object",
            "required": ["api_key", "vendor_id"],
            "properties": {
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "Your Shein API Key"
                },
                "vendor_id": {
                    "type": "string",
                    "title": "Vendor ID",
                    "description": "Your Shein Vendor ID"
                },
                "region": {
                    "type": "string",
                    "title": "Region",
                    "enum": ["NA", "EU", "BR"],
                    "default": "BR"
                }
            }
        },
        auth_config={
            "api_base_url": "https://api.shein.com/vendor/",
            "headers": {
                "Authorization": "Bearer {api_key}",
                "Content-Type": "application/json"
            }
        },
        data_mapping_spec={
            "order_fields": {
                "order_id": "order_id",
                "customer_name": "customer_name",
                "shipping_address": "shipping_address",
                "order_date": "create_time",
                "status": "order_status",
                "items": "order_items"
            },
            "product_fields": {
                "sku": "sku",
                "name": "product_name",
                "price": "unit_price",
                "quantity": "available_stock"
            }
        }
    )


def get_tiktok_shop_module_definition():
    """Get the module definition for TikTok Shop integration"""
    return IntegrationModule(
        id="tiktokshop",
        name="TikTok Shop",
        description="Official integration for TikTok Shop marketplace.",
        version="1.0.0",
        author="NistiPrint Team",
        icon_url="https://app.nistiprint.com.br/assets/img/tiktok.svg",
        category="Marketplace",
        tags=["tiktok", "e-commerce", "orders", "inventory"],
        auth_flow="oauth2",
        config_schema={
            "title": "TikTok Shop Configuration",
            "type": "object",
            "required": ["app_key", "app_secret"],
            "properties": {
                "app_key": { "type": "string", "title": "App Key" },
                "app_secret": { "type": "string", "title": "App Secret" }
            }
        },
        auth_config={
            "oauth_authorization_url": "https://auth.tiktok-shops.com/oauth/authorize",
            "oauth_token_url": "https://auth.tiktok-shops.com/api/v2/token/get"
        }
    )

def get_loja_integrada_module_definition():
    """Get the module definition for Loja Integrada integration"""
    return IntegrationModule(
        id="lojaintegrada",
        name="Loja Integrada",
        description="Integração via API Key com a Loja Integrada.",
        version="1.0.0",
        author="NistiPrint Team",
        icon_url="https://app.nistiprint.com.br/assets/img/lojaintegrada.svg",
        category="E-commerce",
        tags=["lojaintegrada", "api", "orders"],
        auth_flow="api_key",
        config_schema={
            "title": "Configuração Loja Integrada",
            "type": "object",
            "required": ["api_key", "app_key"],
            "properties": {
                "api_key": { "type": "string", "title": "Chave da API" },
                "app_key": { "type": "string", "title": "Chave do Aplicativo" }
            }
        }
    )

def get_bling_module_definition():
    """Get the module definition for Bling V3 integration"""
    return IntegrationModule(
        id="bling",
        name="Bling ERP",
        description="Integração oficial com Bling ERP (API V3) para sincronização de pedidos, estoque e produtos.",
        version="1.0.0",
        author="NistiPrint Team",
        icon_url="https://app.nistiprint.com.br/assets/img/bling.svg",
        category="ERP",
        tags=["bling", "erp", "orders", "inventory", "nfe"],
        auth_flow="oauth2",
        config_schema={
            "title": "Configuração Bling V3",
            "type": "object",
            "required": ["client_id", "client_secret"],
            "properties": {
                "client_id": { "type": "string", "title": "Client ID" },
                "client_secret": { "type": "password", "title": "Client Secret" },
                "cnpj": { "type": "string", "title": "CNPJ (opcional)", "description": "Usado para identificar a conta em sistemas legados" }
            }
        },
        auth_config={
            "oauth_authorization_url": "https://www.bling.com.br/Api/v3/oauth/authorize",
            "oauth_token_url": "https://www.bling.com.br/Api/v3/oauth/token",
            "scopes": ["propostas", "pedidos", "produtos", "estoques"]
        },
        data_mapping_spec={
            "test_endpoint": "/empresas/me/dados-basicos",
            "order_fields": {
                "order_id": "id",
                "customer_name": "contato.nome",
                "total": "total"
            }
        }
    )

def get_all_platform_modules():
    """Get all platform module definitions"""
    return [
        get_bling_module_definition(),
        get_shopee_module_definition(),
        get_amazon_module_definition(),
        get_mercado_livre_module_definition(),
        get_shein_module_definition(),
        get_tiktok_shop_module_definition(),
        get_loja_integrada_module_definition()
    ]




