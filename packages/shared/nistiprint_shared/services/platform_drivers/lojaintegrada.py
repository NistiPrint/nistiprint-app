"""
Loja Integrada Driver
Handles integration with Loja Integrada platform for order and product synchronization
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


def _driver_from_integration(integration: Dict) -> "LojaIntegradaDriver":
    config = {
        **(integration.get("config") or {}),
        **(integration.get("credentials") or {}),
    }
    return LojaIntegradaDriver(config)


def _parse_filter_date(value):
    if isinstance(value, datetime) or value is None:
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def get_order_detail(integration: Dict, order_ids: List[str]) -> Dict:
    if not order_ids:
        return {"error": "Nenhum ID de pedido fornecido."}

    order = _driver_from_integration(integration).get_order_details(str(order_ids[0]))
    return order or {"error": f"Pedido Loja Integrada {order_ids[0]} nao encontrado."}


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    filters = filters or {}
    return _driver_from_integration(integration).get_orders(
        start_date=_parse_filter_date(filters.get("start_date") or filters.get("created_after")),
        end_date=_parse_filter_date(filters.get("end_date") or filters.get("created_before")),
        status=filters.get("status") or filters.get("order_status"),
    )


class LojaIntegradaDriver:
    """Driver for Loja Integrada platform integration"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Loja Integrada driver with configuration
        
        Args:
            config: Dictionary containing Loja Integrada API credentials and settings
        """
        self.config = config
        self.api_key = config.get('api_key')
        self.app_key = config.get('app_key')
        self.api_base_url = 'https://api.awsli.com.br'
        
    def get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication"""
        return {
            'Authorization': f'Basic {self._get_basic_auth()}',
            'Content-Type': 'application/json',
            'X-Api-Key': self.api_key,
            'X-App-Key': self.app_key
        }
    
    def _get_basic_auth(self) -> str:
        """Generate basic auth token from API keys"""
        import base64
        auth_string = f"{self.api_key}:{self.app_key}"
        return base64.b64encode(auth_string.encode()).decode()
    
    def test_connection(self) -> bool:
        """
        Test API connection
        
        Returns:
            bool: True if connection successful
        """
        try:
            url = f"{self.api_base_url}/v1/sistema"
            headers = self.get_headers()
            
            response = requests.get(url, headers=headers)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Error testing Loja Integrada connection: {str(e)}")
            return False
    
    def get_orders(self, start_date: Optional[datetime] = None, 
                   end_date: Optional[datetime] = None,
                   status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get orders from Loja Integrada
        
        Args:
            start_date: Start date for order filtering
            end_date: End date for order filtering
            status: Order status filter
            
        Returns:
            List of order dictionaries
        """
        try:
            url = f"{self.api_base_url}/v1/pedido"
            headers = self.get_headers()
            
            params = {}
            if start_date:
                params['data_inicio'] = start_date.strftime('%d/%m/%Y')
            if end_date:
                params['data_fim'] = end_date.strftime('%d/%m/%Y')
            if status:
                params['situacao_id'] = status
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                orders = data.get('data', [])
                return self._transform_orders(orders)
            else:
                logger.error(f"Error fetching Loja Integrada orders: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Loja Integrada orders: {str(e)}")
            return []
    
    def _transform_orders(self, orders: List[Dict]) -> List[Dict[str, Any]]:
        """
        Transform Loja Integrada orders to standard format
        
        Args:
            orders: Raw orders from Loja Integrada API
            
        Returns:
            Transformed orders list
        """
        transformed_orders = []
        
        for order in orders:
            transformed_order = {
                'order_id': str(order.get('id', '')),
                'customer_name': order.get('cliente', {}).get('nome', ''),
                'shipping_address': self._format_address(order.get('endereco', {})),
                'order_date': self._parse_date(order.get('data')),
                'status': self._map_status(order.get('situacao', {}).get('nome')),
                'total_amount': float(order.get('total', 0)),
                'currency': 'BRL',
                'items': self._transform_items(order.get('produtos', [])),
                'tracking_code': order.get('codigo_rastreio'),
                'raw_data': order
            }
            transformed_orders.append(transformed_order)
            
        return transformed_orders
    
    def _format_address(self, address: Dict) -> str:
        """Format address object to string"""
        parts = [
            address.get('logradouro'),
            address.get('numero'),
            address.get('complemento'),
            address.get('bairro'),
            address.get('cidade'),
            address.get('uf'),
            address.get('cep')
        ]
        return ', '.join(filter(None, parts))
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime object"""
        try:
            return datetime.strptime(date_str, '%d/%m/%Y %H:%M:%S')
        except (ValueError, TypeError):
            return datetime.now()
    
    def _map_status(self, status: str) -> str:
        """Map Loja Integrada status to standard status"""
        status_mapping = {
            'Aguardando Pagamento': 'Pendente',
            'Pago': 'Pago',
            'Faturado': 'Em Produção',
            'Enviado': 'Enviado',
            'Entregue': 'Entregue',
            'Cancelado': 'Cancelado'
        }
        return status_mapping.get(status, status)
    
    def _transform_items(self, items: List[Dict]) -> List[Dict[str, Any]]:
        """Transform order items to standard format"""
        transformed_items = []
        
        for item in items:
            transformed_item = {
                'sku': item.get('codigo', ''),
                'name': item.get('nome', ''),
                'quantity': int(item.get('quantidade', 0)),
                'price': float(item.get('preco_custo', 0)),
                'total_price': float(item.get('subtotal', 0)),
                'image_url': item.get('imagem', ''),
                'attributes': {
                    'weight': item.get('peso'),
                    'dimensions': item.get('dimensoes')
                }
            }
            transformed_items.append(transformed_item)
            
        return transformed_items
    
    def get_products(self) -> List[Dict[str, Any]]:
        """
        Get products from Loja Integrada
        
        Returns:
            List of product dictionaries
        """
        try:
            url = f"{self.api_base_url}/v1/produto"
            headers = self.get_headers()
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                products = data.get('data', [])
                return self._transform_products(products)
            else:
                logger.error(f"Error fetching Loja Integrada products: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Loja Integrada products: {str(e)}")
            return []
    
    def _transform_products(self, products: List[Dict]) -> List[Dict[str, Any]]:
        """Transform Loja Integrada products to standard format"""
        transformed_products = []
        
        for product in products:
            transformed_product = {
                'sku': product.get('codigo', ''),
                'name': product.get('nome', ''),
                'description': product.get('descricao', ''),
                'price': float(product.get('preco', 0)),
                'stock': int(product.get('estoque', 0)),
                'category': product.get('categoria', {}).get('nome', ''),
                'image_url': product.get('imagem', ''),
                'status': product.get('situacao', ''),
                'attributes': {
                    'weight': product.get('peso'),
                    'dimensions': product.get('dimensoes'),
                    'ncm': product.get('ncm')
                },
                'raw_data': product
            }
            transformed_products.append(transformed_product)
            
        return transformed_products
    
    def update_order_status(self, order_id: str, status: str, 
                           tracking_code: Optional[str] = None) -> bool:
        """
        Update order status in Loja Integrada
        
        Args:
            order_id: Order ID
            status: New status
            tracking_code: Optional tracking code
            
        Returns:
            bool: True if update successful
        """
        try:
            url = f"{self.api_base_url}/v1/pedido/{order_id}"
            headers = self.get_headers()
            
            data = {
                'situacao_id': self._get_status_id(status)
            }
            
            if tracking_code:
                data['codigo_rastreio'] = tracking_code
            
            response = requests.put(url, headers=headers, json=data)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Error updating Loja Integrada order status: {str(e)}")
            return False
    
    def _get_status_id(self, status_name: str) -> int:
        """Get status ID by name"""
        status_ids = {
            'Pendente': 1,
            'Pago': 2,
            'Em Produção': 3,
            'Enviado': 4,
            'Entregue': 5,
            'Cancelado': 6
        }
        return status_ids.get(status_name, 1)
    
    def get_order_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed order information
        
        Args:
            order_id: Order ID
            
        Returns:
            Order details dictionary or None
        """
        try:
            url = f"{self.api_base_url}/v1/pedido/{order_id}"
            headers = self.get_headers()
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                order = data.get('data', {})
                return self._transform_orders([order])[0] if order else None
            else:
                logger.error(f"Error fetching Loja Integrada order details: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting Loja Integrada order details: {str(e)}")
            return None
