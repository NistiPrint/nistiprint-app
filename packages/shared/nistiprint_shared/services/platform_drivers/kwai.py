"""
Kwai Marketplace Driver
Handles integration with Kwai marketplace for order and product synchronization
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


def _driver_from_integration(integration: Dict) -> "KwaiDriver":
    config = {
        **(integration.get("config") or {}),
        **(integration.get("credentials") or {}),
    }
    if integration.get("access_token"):
        config["access_token"] = integration.get("access_token")
    if integration.get("refresh_token"):
        config["refresh_token"] = integration.get("refresh_token")
    return KwaiDriver(config)


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

    orders = _driver_from_integration(integration).get_orders()
    for order in orders:
        if str(order.get("order_id")) == str(order_ids[0]):
            return order
    return {"error": f"Pedido Kwai {order_ids[0]} nao encontrado."}


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    filters = filters or {}
    return _driver_from_integration(integration).get_orders(
        start_date=_parse_filter_date(filters.get("start_date") or filters.get("created_after")),
        end_date=_parse_filter_date(filters.get("end_date") or filters.get("created_before")),
        status=filters.get("status") or filters.get("order_status"),
    )


class KwaiDriver:
    """Driver for Kwai marketplace integration"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Kwai driver with configuration
        
        Args:
            config: Dictionary containing Kwai API credentials and settings
        """
        self.config = config
        self.app_key = config.get('app_key')
        self.app_secret = config.get('app_secret')
        self.access_token = config.get('access_token')
        self.refresh_token = config.get('refresh_token')
        self.region = config.get('region', 'BR')
        self.api_base_url = self._get_api_base_url()
        
    def _get_api_base_url(self) -> str:
        """Get API base URL based on region"""
        region_urls = {
            'BR': 'https://open.kwaishope.com.br',
            'US': 'https://open.kwaishope.com',
            'MX': 'https://open.kwaishope.com.mx'
        }
        return region_urls.get(self.region, 'https://open.kwaishope.com.br')
    
    def authenticate(self) -> bool:
        """
        Authenticate with Kwai API
        
        Returns:
            bool: True if authentication successful
        """
        try:
            auth_url = f"{self.api_base_url}/oauth2/token"
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token,
                'app_key': self.app_key,
                'app_secret': self.app_secret
            }
            
            response = requests.post(auth_url, data=data)
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                self.refresh_token = token_data.get('refresh_token')
                return True
            else:
                logger.error(f"Kwai authentication failed: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error authenticating with Kwai: {str(e)}")
            return False
    
    def get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication"""
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
            'x-app-key': self.app_key
        }
    
    def test_connection(self) -> bool:
        """
        Test API connection
        
        Returns:
            bool: True if connection successful
        """
        try:
            url = f"{self.api_base_url}/api/v1/shop/info"
            headers = self.get_headers()
            
            response = requests.get(url, headers=headers)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Error testing Kwai connection: {str(e)}")
            return False
    
    def get_orders(self, start_date: Optional[datetime] = None, 
                   end_date: Optional[datetime] = None,
                   status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get orders from Kwai marketplace
        
        Args:
            start_date: Start date for order filtering
            end_date: End date for order filtering
            status: Order status filter
            
        Returns:
            List of order dictionaries
        """
        try:
            url = f"{self.api_base_url}/api/v1/orders/list"
            headers = self.get_headers()
            
            params = {}
            if start_date:
                params['start_time'] = int(start_date.timestamp())
            if end_date:
                params['end_time'] = int(end_date.timestamp())
            if status:
                params['order_status'] = status
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return self._transform_orders(data.get('data', []))
            else:
                logger.error(f"Error fetching Kwai orders: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Kwai orders: {str(e)}")
            return []
    
    def _transform_orders(self, orders: List[Dict]) -> List[Dict[str, Any]]:
        """
        Transform Kwai orders to standard format
        
        Args:
            orders: Raw orders from Kwai API
            
        Returns:
            Transformed orders list
        """
        transformed_orders = []
        
        for order in orders:
            transformed_order = {
                'order_id': order.get('order_sn'),
                'customer_name': order.get('receiver_name'),
                'shipping_address': self._format_address(order.get('receiver_address', {})),
                'order_date': datetime.fromtimestamp(order.get('create_time', 0)),
                'status': self._map_status(order.get('order_status')),
                'total_amount': order.get('total_amount', 0),
                'currency': order.get('currency', 'BRL'),
                'items': self._transform_items(order.get('items', [])),
                'tracking_code': order.get('tracking_number'),
                'raw_data': order
            }
            transformed_orders.append(transformed_order)
            
        return transformed_orders
    
    def _format_address(self, address: Dict) -> str:
        """Format address object to string"""
        parts = [
            address.get('address'),
            address.get('address_detail'),
            address.get('city'),
            address.get('state'),
            address.get('zipcode'),
            address.get('country')
        ]
        return ', '.join(filter(None, parts))
    
    def _map_status(self, kwai_status: str) -> str:
        """Map Kwai status to standard status"""
        status_mapping = {
            'UNPAID': 'Pendente',
            'PAID': 'Pago',
            'READY_TO_SHIP': 'Pronto para Envio',
            'SHIPPED': 'Enviado',
            'COMPLETED': 'Entregue',
            'CANCELLED': 'Cancelado'
        }
        return status_mapping.get(kwai_status, 'Desconhecido')
    
    def _transform_items(self, items: List[Dict]) -> List[Dict[str, Any]]:
        """Transform order items to standard format"""
        transformed_items = []
        
        for item in items:
            transformed_item = {
                'sku': item.get('sku'),
                'name': item.get('product_name'),
                'quantity': item.get('quantity', 0),
                'price': item.get('price', 0),
                'total_price': item.get('total_amount', 0),
                'image_url': item.get('product_image'),
                'attributes': item.get('product_attributes', {})
            }
            transformed_items.append(transformed_item)
            
        return transformed_items
    
    def get_products(self) -> List[Dict[str, Any]]:
        """
        Get products from Kwai marketplace
        
        Returns:
            List of product dictionaries
        """
        try:
            url = f"{self.api_base_url}/api/v1/products/list"
            headers = self.get_headers()
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                return self._transform_products(data.get('data', []))
            else:
                logger.error(f"Error fetching Kwai products: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Kwai products: {str(e)}")
            return []
    
    def _transform_products(self, products: List[Dict]) -> List[Dict[str, Any]]:
        """Transform Kwai products to standard format"""
        transformed_products = []
        
        for product in products:
            transformed_product = {
                'sku': product.get('sku'),
                'name': product.get('product_name'),
                'description': product.get('description'),
                'price': product.get('price', 0),
                'stock': product.get('stock', 0),
                'category': product.get('category_name'),
                'image_url': product.get('main_image'),
                'status': product.get('status'),
                'attributes': product.get('attributes', {}),
                'raw_data': product
            }
            transformed_products.append(transformed_product)
            
        return transformed_products
    
    def update_order_status(self, order_id: str, status: str, 
                           tracking_code: Optional[str] = None) -> bool:
        """
        Update order status in Kwai
        
        Args:
            order_id: Kwai order ID
            status: New status
            tracking_code: Optional tracking code
            
        Returns:
            bool: True if update successful
        """
        try:
            url = f"{self.api_base_url}/api/v1/orders/update"
            headers = self.get_headers()
            
            data = {
                'order_sn': order_id,
                'order_status': status
            }
            
            if tracking_code:
                data['tracking_number'] = tracking_code
            
            response = requests.post(url, headers=headers, json=data)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Error updating Kwai order status: {str(e)}")
            return False
