"""Strict account-local dispatch. No ERP or default-account fallback."""
from importlib import import_module

CAPABILITIES = {
    'shopee_escrow': 'shopee', 'shopee_product': 'shopee', 'shopee_ads': 'shopee',
    'ml_visits': 'mercadolivre', 'ml_ads': 'mercadolivre', 'ml_billing': 'mercadolivre',
    'bling_history': 'bling',
}


def driver_for(provider):
    if provider not in {'shopee', 'mercadolivre', 'bling'}:
        raise ValueError('Marketplace sem capacidade de inteligência')
    return import_module(f'nistiprint_shared.services.platform_drivers.{provider}_insights')


def extract(source):
    order = source['order']
    provider = str(order.get('marketplace_module_id') or order.get('origem') or '').lower()
    if provider not in {'shopee', 'mercadolivre', 'bling'}:
        from .insights_contract import OrderInsights
        return OrderInsights(provider, order.get('marketplace_integration_id'), str(order['id']), {})
    return driver_for(provider).extract(source)
