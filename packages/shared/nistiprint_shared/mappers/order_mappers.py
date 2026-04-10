from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

def safe_float(value: Any, default: float = 0.0) -> float:
    """Converte valores de forma segura, tratando se vierem como dicionários da API."""
    if value is None: return default
    if isinstance(value, (int, float)): return float(value)
    if isinstance(value, dict):
        # Tenta pegar campos comuns de valor em objetos (Bling v3 style)
        for k in ['valor', 'total', 'quantidade']:
            if k in value: return safe_float(value[k], default)
        return default
    try:
        return float(str(value).replace(',', '.'))
    except:
        return default


def derivar_modalidade_do_servico(
    servico_logistico: str,
    canal_venda_id: Optional[int] = None,
    is_flex: bool = False,
    fulfillment: bool = False
) -> str:
    """
    Deriva modalidade logística a partir do servico_logístico.
    
    Prioridade:
    1. Tenta usar canal_modalidade_service se canal_venda_id disponível
    2. Fallback para detecção por palavras-chave (legado)
    3. Fallback para flags is_flex/fulfillment
    4. Default: STANDARD
    
    Args:
        servico_logistico: String do serviço logístico
        canal_venda_id: ID do canal (opcional, para mapeamento configurável)
        is_flex: Flag de flex (fallback)
        fulfillment: Flag de fulfillment (fallback)
    
    Returns:
        Modalidade: STANDARD, EXPRESS, FULFILLMENT, RETIRADA
    """
    # Tentar mapeamento configurável se canal disponível
    if canal_venda_id:
        try:
            from nistiprint_shared.services.canal_modalidade_service import canal_modalidade_service
            modalidade = canal_modalidade_service.derivar_modalidade(
                canal_venda_id,
                servico_logistico
            )
            if modalidade:
                logger.debug(
                    "Modalidade derivada via mapeamento: %s (canal %s, servico: %s)",
                    modalidade,
                    canal_venda_id,
                    servico_logistico
                )
                return modalidade
        except ImportError:
            logger.warning("canal_modalidade_service não disponível, usando fallback")
        except Exception as e:
            logger.warning(
                "Erro ao derivar modalidade via service: %s. Usando fallback.",
                str(e)
            )
    
    # Fallback: detecção por palavras-chave (legado)
    servico_upper = str(servico_logistico).upper() if servico_logistico else ""
    
    # EXPRESS
    if any(x in servico_upper for x in ["FLEX", "DIRETA", "LOGGI", "RÁPIDA", "RAPIDA", "EXPRESS"]):
        return 'EXPRESS'
    
    # FULFILLMENT
    if any(x in servico_upper for x in ["FULL", "FULFILLMENT", "REPOSIÇÃO", "REPOSICAO"]):
        return 'FULFILLMENT'
    
    # RETIRADA
    if any(x in servico_upper for x in ["RETIRADA", "PICKUP", "BALCÃO", "BALCAO"]):
        return 'RETIRADA'
    
    # Fallback para flags
    if is_flex:
        return 'EXPRESS'
    if fulfillment:
        return 'FULFILLMENT'
    
    # Default
    return 'STANDARD'

class BaseOrderMapper:
    """
    Interface base para normalização de pedidos entre diferentes plataformas.
    """
    @staticmethod
    def map(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses devem implementar map()")

    @staticmethod
    def _to_iso(dt: Any) -> Optional[str]:
        if not dt: return None
        if isinstance(dt, (int, float)): # Timestamp
            return datetime.fromtimestamp(dt, tz=timezone.utc).isoformat()
        if isinstance(dt, str):
            if dt.startswith('0000'): return None
            return dt
        return str(dt)

class BlingMapper(BaseOrderMapper):
    """Normalizador de Pedidos do Bling com conversão segura."""

    @staticmethod
    def map(raw: Dict[str, Any], canal_venda_id: Optional[int] = None) -> Dict[str, Any]:
        contato = raw.get('contato', {})
        transporte = raw.get('transporte', {})
        volumes = transporte.get('volumes', [])
        servico = volumes[0].get('servico', '') if volumes else ""
        
        # Derivar modalidade logística
        is_flex_legacy = any(x in str(servico).upper() for x in ["FLEX", "DIRETA", "LOGGI"])
        modalidade = derivar_modalidade_do_servico(
            servico,
            canal_venda_id=canal_venda_id,
            is_flex=is_flex_legacy
        )

        return {
            "id": str(raw.get('id')),
            "source": "BLING",
            "external_id": raw.get('numeroLoja') or f"BLING-{raw.get('numero')}",
            "status": str(raw.get('situacao', {}).get('id')),
            "created_at": BaseOrderMapper._to_iso(raw.get('data')),
            "customer": {
                "id": contato.get('id'),
                "name": contato.get('nome'),
                "document": contato.get('numeroDocumento'),
                "email": contato.get('email'),
                "phone": contato.get('telefone') or contato.get('celular')
            },
            "shipping": {
                "service": servico,
                "is_flex": is_flex_legacy,
                "modalidade_logistica": modalidade,
                "estimated_delivery": BaseOrderMapper._to_iso(raw.get('dataPrevista')),
                "address": raw.get('enderecoEntrega', {})
            },
            "totals": {
                "subtotal": safe_float(raw.get('totalProdutos')),
                "shipping": safe_float(raw.get('valorFrete')),
                "discount": safe_float(raw.get('desconto')),
                "total": safe_float(raw.get('total'))
            },
            "items": [
                {
                    "sku": item.get('codigo'),
                    "name": item.get('descricao'),
                    "quantity": safe_float(item.get('quantidade'), 1.0),
                    "unit_price": safe_float(item.get('valor')),
                    "subtotal": safe_float(item.get('valor')) * safe_float(item.get('quantidade'), 1.0)
                } for item in raw.get('itens', [])
            ]
        }

class ShopeeMapper(BaseOrderMapper):
    """Normalizador de Pedidos da Shopee com conversão segura."""

    @staticmethod
    def map(raw: Dict[str, Any], canal_venda_id: Optional[int] = None) -> Dict[str, Any]:
        recipient = raw.get('recipient_address', {})
        shipping_carrier = raw.get('shipping_carrier', '')
        
        # Derivar modalidade logística
        is_flex_legacy = 'ENTREGA RÁPIDA' in str(shipping_carrier).upper() or 'ENTREGA RAPIDA' in str(shipping_carrier).upper()
        modalidade = derivar_modalidade_do_servico(
            shipping_carrier,
            canal_venda_id=canal_venda_id,
            is_flex=is_flex_legacy
        )

        return {
            "id": raw.get('order_sn'),
            "source": "SHOPEE",
            "external_id": raw.get('order_sn'),
            "status": raw.get('order_status'),
            "created_at": BaseOrderMapper._to_iso(raw.get('create_time')),
            "customer": {
                "name": recipient.get('name') or raw.get('buyer_username'),
                "phone": recipient.get('phone'),
                "email": None,
                "username": raw.get('buyer_username')
            },
            "shipping": {
                "service": shipping_carrier,
                "is_flex": is_flex_legacy,
                "modalidade_logistica": modalidade,
                "estimated_delivery": BaseOrderMapper._to_iso(raw.get('ship_by_date')),
                "address": recipient
            },
            "totals": {
                "total": safe_float(raw.get('total_amount'))
            },
            "items": [
                {
                    "sku": item.get('item_sku') or item.get('model_sku'),
                    "name": item.get('item_name'),
                    "quantity": safe_float(item.get('model_quantity_purchased'), 1.0),
                    "unit_price": safe_float(item.get('model_original_price')),
                    "subtotal": safe_float(item.get('model_original_price')) * safe_float(item.get('model_quantity_purchased'), 1.0)
                } for item in raw.get('item_list', [])
            ]
        }
