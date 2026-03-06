"""
Interface comum para todos os drivers de plataforma.
Define os métodos que cada driver deve implementar.
"""

from typing import List, Dict, Optional


def get_order_detail(integration: Dict, order_ids: List[str]) -> Dict:
    """
    Método para obter detalhes de um pedido específico.
    
    Args:
        integration: Dicionário contendo informações da integração (credenciais, configurações, etc.)
        order_ids: Lista de IDs dos pedidos a serem consultados
        
    Returns:
        Dicionário com os detalhes do(s) pedido(s) ou mensagem de erro
    """
    raise NotImplementedError("Este método deve ser implementado pelo driver específico")


def get_orders_list(integration: Dict, filters: Optional[Dict] = None) -> List[Dict]:
    """
    Método para obter lista de pedidos com base em filtros.
    
    Args:
        integration: Dicionário contendo informações da integração (credenciais, configurações, etc.)
        filters: Dicionário opcional com filtros para a consulta (datas, status, etc.)
        
    Returns:
        Lista de dicionários com os pedidos ou mensagem de erro
    """
    raise NotImplementedError("Este método deve ser implementado pelo driver específico")


def get_product_detail(integration: Dict, product_ids: List[str]) -> Dict:
    """
    Método para obter detalhes de um produto específico.
    
    Args:
        integration: Dicionário contendo informações da integração (credenciais, configurações, etc.)
        product_ids: Lista de IDs dos produtos a serem consultados
        
    Returns:
        Dicionário com os detalhes do(s) produto(s) ou mensagem de erro
    """
    raise NotImplementedError("Este método deve ser implementado pelo driver específico")

