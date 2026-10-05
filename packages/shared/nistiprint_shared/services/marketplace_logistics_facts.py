"""Fatos de envio: horario fisico nao pode vir do fechamento da compra."""
from datetime import datetime


def normalize_sla(value):
    if isinstance(value, list):
        value = value[0] if value else {}
    return value if isinstance(value, dict) and not value.get('error') else {}


def meli_departed(shipment):
    return shipment.get('status') in ('shipped', 'delivered', 'not_delivered') or shipment.get('substatus') in (
        'picked_up', 'authorized_by_carrier', 'in_hub')


def meli_dispatch_timestamp(detail):
    shipment = (detail or {}).get('shipment') or {}
    if not meli_departed(shipment):
        return None
    values = [shipment.get('date_shipped'), (shipment.get('status_history') or {}).get('date_shipped')]
    for row in shipment.get('_history') or []:
        if isinstance(row, dict) and meli_departed(row):
            values.append(row.get('date') or row.get('date_created'))
    parsed = []
    for value in values:
        if value:
            try:
                dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                if dt.tzinfo is not None:
                    parsed.append(dt)
            except (ValueError, TypeError):
                pass
    return min(parsed).isoformat() if parsed else None
