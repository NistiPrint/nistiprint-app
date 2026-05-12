"""
Amazon Fulfillment Driver
Handles integration with Amazon FBA (Fulfillment by Amazon) for order and product synchronization
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import requests

logger = logging.getLogger(__name__)


def _driver_from_integration(integration: Dict) -> "AmazonFulfillmentDriver":
    config = {
        **(integration.get("config") or {}),
        **(integration.get("credentials") or {}),
    }
    if integration.get("access_token"):
        config["access_token"] = integration.get("access_token")
    if integration.get("refresh_token"):
        config["refresh_token"] = integration.get("refresh_token")
    return AmazonFulfillmentDriver(config)


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

    driver = _driver_from_integration(integration)
    items = driver.get_order_items(str(order_ids[0]))
    return {"order_id": str(order_ids[0]), "items": items}


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    filters = filters or {}
    return _driver_from_integration(integration).get_orders(
        start_date=_parse_filter_date(filters.get("start_date") or filters.get("created_after")),
        end_date=_parse_filter_date(filters.get("end_date") or filters.get("created_before")),
        status=filters.get("status") or filters.get("order_status"),
    )


class AmazonFulfillmentDriver:
    """Driver for Amazon FBA integration"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Amazon FBA driver with configuration
        
        Args:
            config: Dictionary containing Amazon API credentials and settings
        """
        self.config = config
        self.seller_id = config.get('seller_id')
        self.mws_auth_token = config.get('mws_auth_token')
        self.aws_access_key = config.get('aws_access_key')
        self.secret_key = config.get('secret_key')
        self.marketplace_id = config.get('marketplace_id', 'A1AM78C64UM0Y8')  # Brazil default
        self.region = config.get('region', 'us-east-1')
        self.api_base_url = f"https://sellingpartnerapi-na.amazon.com"
        
    def get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication"""
        return {
            'Authorization': f'Bearer {self.config.get("access_token")}',
            'Content-Type': 'application/json',
            'x-amz-access-token': self.config.get("access_token")
        }
    
    def test_connection(self) -> bool:
        """
        Test API connection
        
        Returns:
            bool: True if connection successful
        """
        try:
            url = f"{self.api_base_url}/orders/v0/orders"
            headers = self.get_headers()
            params = {
                'MarketplaceIds': self.marketplace_id,
                'CreatedAfter': (datetime.now() - timedelta(days=1)).isoformat()
            }
            
            response = requests.get(url, headers=headers, params=params)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"Error testing Amazon FBA connection: {str(e)}")
            return False
    
    def get_orders(self, start_date: Optional[datetime] = None, 
                   end_date: Optional[datetime] = None,
                   status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get orders from Amazon FBA
        
        Args:
            start_date: Start date for order filtering
            end_date: End date for order filtering
            status: Order status filter
            
        Returns:
            List of order dictionaries
        """
        try:
            url = f"{self.api_base_url}/orders/v0/orders"
            headers = self.get_headers()
            
            params = {
                'MarketplaceIds': self.marketplace_id
            }
            
            if start_date:
                params['CreatedAfter'] = start_date.isoformat()
            if end_date:
                params['CreatedBefore'] = end_date.isoformat()
            if status:
                params['OrderStatuses'] = status
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                orders = data.get('payload', {}).get('Orders', [])
                return self._transform_orders(orders)
            else:
                logger.error(f"Error fetching Amazon FBA orders: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Amazon FBA orders: {str(e)}")
            return []
    
    def _transform_orders(self, orders: List[Dict]) -> List[Dict[str, Any]]:
        """
        Transform Amazon FBA orders to standard format
        
        Args:
            orders: Raw orders from Amazon API
            
        Returns:
            Transformed orders list
        """
        transformed_orders = []
        
        for order in orders:
            transformed_order = {
                'order_id': order.get('AmazonOrderId'),
                'customer_name': order.get('BuyerInfo', {}).get('BuyerName', ''),
                'shipping_address': self._format_address(order.get('ShippingAddress', {})),
                'order_date': self._parse_date(order.get('PurchaseDate')),
                'status': self._map_status(order.get('OrderStatus')),
                'total_amount': float(order.get('OrderTotal', {}).get('Amount', 0)),
                'currency': order.get('OrderTotal', {}).get('CurrencyCode', 'BRL'),
                'fulfillment_channel': order.get('FulfillmentChannel', 'MFN'),  # FBA or MFN
                'items': [],  # Will be populated with get_order_items
                'tracking_code': None,  # FBA tracking codes come from fulfillment data
                'raw_data': order
            }
            transformed_orders.append(transformed_order)
            
        return transformed_orders
    
    def _format_address(self, address: Dict) -> str:
        """Format address object to string"""
        parts = [
            address.get('AddressLine1'),
            address.get('AddressLine2'),
            address.get('AddressLine3'),
            address.get('City'),
            address.get('StateOrRegion'),
            address.get('PostalCode'),
            address.get('CountryCode')
        ]
        return ', '.join(filter(None, parts))
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse ISO date string to datetime object"""
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return datetime.now()
    
    def _map_status(self, amazon_status: str) -> str:
        """Map Amazon status to standard status"""
        status_mapping = {
            'Pending': 'Pendente',
            'Unshipped': 'Pago',
            'PartiallyShipped': 'Em Produção',
            'Shipped': 'Enviado',
            'Delivered': 'Entregue',
            'Canceled': 'Cancelado'
        }
        return status_mapping.get(amazon_status, 'Desconhecido')
    
    def get_order_items(self, order_id: str) -> List[Dict[str, Any]]:
        """
        Get items for a specific order
        
        Args:
            order_id: Amazon order ID
            
        Returns:
            List of order items
        """
        try:
            url = f"{self.api_base_url}/orders/v0/orders/{order_id}/orderItems"
            headers = self.get_headers()
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('payload', {}).get('OrderItems', [])
                return self._transform_items(items)
            else:
                logger.error(f"Error fetching Amazon FBA order items: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Amazon FBA order items: {str(e)}")
            return []
    
    def _transform_items(self, items: List[Dict]) -> List[Dict[str, Any]]:
        """Transform order items to standard format"""
        transformed_items = []
        
        for item in items:
            transformed_item = {
                'sku': item.get('SellerSKU'),
                'name': item.get('Title'),
                'quantity': int(item.get('QuantityOrdered', 0)),
                'price': float(item.get('ItemPrice', {}).get('Amount', 0)),
                'total_price': float(item.get('ItemPrice', {}).get('Amount', 0)) * int(item.get('QuantityOrdered', 0)),
                'image_url': '',  # Amazon doesn't provide image in order items
                'attributes': {
                    'asin': item.get('ASIN'),
                    'order_item_id': item.get('OrderItemId')
                }
            }
            transformed_items.append(transformed_item)
            
        return transformed_items
    
    def get_inventory(self) -> List[Dict[str, Any]]:
        """
        Get FBA inventory levels
        
        Returns:
            List of inventory data
        """
        try:
            url = f"{self.api_base_url}/fba/inventory/v1/summaries"
            headers = self.get_headers()
            params = {
                'marketplaceIds': self.marketplace_id,
                'details': True
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                inventory = data.get('payload', {}).get('inventorySummaries', [])
                return self._transform_inventory(inventory)
            else:
                logger.error(f"Error fetching Amazon FBA inventory: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Amazon FBA inventory: {str(e)}")
            return []
    
    def _transform_inventory(self, inventory: List[Dict]) -> List[Dict[str, Any]]:
        """Transform inventory data to standard format"""
        transformed_inventory = []
        
        for item in inventory:
            transformed_item = {
                'sku': item.get('sellerSku'),
                'fn_sku': item.get('fnSku'),
                'total_quantity': int(item.get('totalQuantity', 0)),
                'fulfillable_quantity': int(item.get('fulfillableQuantity', 0)),
                'inbound_working_quantity': int(item.get('inboundWorkingQuantity', 0)),
                'inbound_shipped_quantity': int(item.get('inboundShippedQuantity', 0)),
                'reserved_quantity': int(item.get('reservedQuantity', 0)),
                'unfulfillable_quantity': int(item.get('unfulfillableQuantity', 0)),
                'last_updated': self._parse_date(item.get('lastUpdatedTime')),
                'raw_data': item
            }
            transformed_inventory.append(transformed_item)
            
        return transformed_inventory
    
    def get_fulfillment_orders(self) -> List[Dict[str, Any]]:
        """
        Get FBA fulfillment orders (shipping information)
        
        Returns:
            List of fulfillment orders with tracking data
        """
        try:
            url = f"{self.api_base_url}/fba/outbound/2020-07-01/fulfillmentOrders"
            headers = self.get_headers()
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                orders = data.get('payload', {}).get('FulfillmentOrders', [])
                return self._transform_fulfillment_orders(orders)
            else:
                logger.error(f"Error fetching Amazon FBA fulfillment orders: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting Amazon FBA fulfillment orders: {str(e)}")
            return []
    
    def _transform_fulfillment_orders(self, orders: List[Dict]) -> List[Dict[str, Any]]:
        """Transform fulfillment orders to standard format"""
        transformed_orders = []
        
        for order in orders:
            transformed_order = {
                'fulfillment_order_id': order.get('SellerFulfillmentOrderId'),
                'order_id': order.get('DisplayableOrderId'),
                'fulfillment_status': order.get('FulfillmentOrderStatus'),
                'shipping_address': self._format_address(order.get('DestinationAddress', {})),
                'tracking_codes': [item.get('TrackingNumber') for item in order.get('FulfillmentShipment', {}).get('PackageList', [])],
                'shipping_method': order.get('FulfillmentShippingMethod'),
                'estimated_arrival': order.get('EstimatedArrivalDate'),
                'raw_data': order
            }
            transformed_orders.append(transformed_order)
            
        return transformed_orders
    
    def update_order_status(self, order_id: str, status: str) -> bool:
        """
        Update order status in Amazon (limited for FBA orders)
        
        Args:
            order_id: Amazon order ID
            status: New status
            
        Returns:
            bool: True if update successful
        """
        # FBA orders are managed by Amazon, status updates are limited
        logger.warning(f"Status updates not supported for FBA order {order_id}")
        return False
