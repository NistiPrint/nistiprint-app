#!/usr/bin/env python3
"""
Script para backfill da tabela pedidos com dados de tabelas externas.

Este script busca pedidos em pedidos_bling e pedidos_shopee que não existem
na tabela pedidos e os insere usando o order_service.upsert_order.

Uso:
    python scripts/backfill_pedidos_unificados.py
"""

import sys
import os
import logging

# Adicionar path para imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.order_service import order_service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_existing_pedidos():
    """Retorna conjuntos de codigo_pedido_externo e numero_pedido existentes em pedidos."""
    try:
        result = supabase_db.table('pedidos').select('codigo_pedido_externo, numero_pedido').execute()
        existing_codigo_externo = {row['codigo_pedido_externo'] for row in result.data if row.get('codigo_pedido_externo')}
        existing_numero_pedido = {row['numero_pedido'] for row in result.data if row.get('numero_pedido')}
        return existing_codigo_externo, existing_numero_pedido
    except Exception as e:
        logger.error(f"Erro ao buscar pedidos existentes: {e}")
        return set(), set()


def backfill_from_pedidos_bling(existing_codigo_externo, existing_numero_pedido):
    """Backfill de pedidos_bling para pedidos."""
    logger.info("=" * 60)
    logger.info("BACKFILL: pedidos_bling → pedidos")
    logger.info("=" * 60)
    
    try:
        # Buscar todos os pedidos_bling
        result = supabase_db.table('pedidos_bling').select('*').execute()
        
        if not result.data:
            logger.info("Nenhum pedido em pedidos_bling encontrado.")
            return 0
        
        # Filtrar pedidos que não existem em pedidos (por codigo_pedido_externo ou numero_pedido)
        new_orders = [
            p for p in result.data 
            if p.get('numero_loja') and 
            p.get('numero_loja') not in existing_codigo_externo and
            p.get('numero_pedido') and 
            p.get('numero_pedido') not in existing_numero_pedido
        ]
        
        logger.info(f"Total pedidos_bling: {len(result.data)}")
        logger.info(f"Pedidos já em pedidos: {len(result.data) - len(new_orders)}")
        logger.info(f"Pedidos para backfill: {len(new_orders)}")
        
        success_count = 0
        error_count = 0
        
        for pedido_bling in new_orders:
            try:
                raw_payload = pedido_bling.get('raw_payload', {})
                
                # Se raw_payload for string (JSON), parse para dict
                if isinstance(raw_payload, str):
                    try:
                        import json
                        raw_payload = json.loads(raw_payload)
                    except:
                        raw_payload = {}
                
                # Se não tiver raw_payload, construir do pedido_bling
                if not raw_payload:
                    raw_payload = {
                        'numero': pedido_bling.get('numero_pedido'),
                        'numeroLoja': pedido_bling.get('numero_loja'),
                        'situacao': {'id': pedido_bling.get('situacao_pedido')},
                        'contato': {
                            'nome': pedido_bling.get('cliente_nome'),
                            'numeroDocumento': pedido_bling.get('cliente_documento')
                        },
                        'totalProdutos': pedido_bling.get('total_pedido', 0),
                        'loja': {'id': pedido_bling.get('loja_id')}
                    }
                
                order_data = {
                    'codigo_pedido_externo': pedido_bling.get('numero_loja'),
                    'numero_pedido': pedido_bling.get('numero_pedido'),
                    'cliente_nome': pedido_bling.get('cliente_nome'),
                    'cliente_documento': pedido_bling.get('cliente_documento'),
                    'origem': 'BLING',
                    'total_pedido': pedido_bling.get('total_pedido', 0),
                    'personalizado': pedido_bling.get('personalizado', False)
                }
                
                # Buscar itens do pedido
                itens_result = supabase_db.table('itens_pedido_bling').select('*').eq('pedido_bling_id', pedido_bling['id']).execute()
                items = []
                for item in itens_result.data:
                    items.append({
                        'sku_externo': item.get('codigo'),
                        'descricao': item.get('descricao'),
                        'quantidade': item.get('quantidade', 1),
                        'preco_unitario': item.get('valor', 0),
                        'personalizado': item.get('personalizado', False)
                    })
                
                order_service.upsert_order(
                    order_data=order_data,
                    platform='BLING',
                    platform_order_id=pedido_bling.get('numero_loja'),
                    raw_payload=raw_payload,
                    items=items if items else None
                )
                
                success_count += 1
                if success_count % 100 == 0:
                    logger.info(f"Progresso: {success_count}/{len(new_orders)}")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"Erro ao processar pedido {pedido_bling.get('numero_loja')}: {e}")
        
        logger.info(f"✅ pedidos_bling: {success_count} inseridos, {error_count} erros")
        return success_count
        
    except Exception as e:
        logger.error(f"Erro no backfill de pedidos_bling: {e}")
        return 0


def backfill_from_pedidos_shopee(existing_codigo_externo, existing_numero_pedido):
    """Backfill de pedidos_shopee para pedidos."""
    logger.info("=" * 60)
    logger.info("BACKFILL: pedidos_shopee → pedidos")
    logger.info("=" * 60)
    
    try:
        # Buscar todos os pedidos_shopee
        result = supabase_db.table('pedidos_shopee').select('*').execute()
        
        if not result.data:
            logger.info("Nenhum pedido em pedidos_shopee encontrado.")
            return 0
        
        # Filtrar pedidos que não existem em pedidos (por codigo_pedido_externo ou numero_pedido)
        new_orders = [
            p for p in result.data 
            if p.get('codigo_pedido') and 
            p.get('codigo_pedido') not in existing_codigo_externo and
            p.get('codigo_pedido') and 
            p.get('codigo_pedido') not in existing_numero_pedido
        ]
        
        logger.info(f"Total pedidos_shopee: {len(result.data)}")
        logger.info(f"Pedidos já em pedidos: {len(result.data) - len(new_orders)}")
        logger.info(f"Pedidos para backfill: {len(new_orders)}")
        
        success_count = 0
        error_count = 0
        
        for pedido_shopee in new_orders:
            try:
                raw_payload = pedido_shopee.get('raw_payload', {})
                
                # Se raw_payload for string (JSON), parse para dict
                if isinstance(raw_payload, str):
                    try:
                        import json
                        raw_payload = json.loads(raw_payload)
                    except:
                        raw_payload = {}
                
                # Se não tiver raw_payload, construir do pedido_shopee
                if not raw_payload:
                    raw_payload = {
                        'order_sn': pedido_shopee.get('codigo_pedido'),
                        'status_original': pedido_shopee.get('status'),
                        'date_created': pedido_shopee.get('data_pedido'),
                        'total': pedido_shopee.get('total_pedido'),
                        'buyer_username': pedido_shopee.get('informacoes_comprador', {}).get('username') if isinstance(pedido_shopee.get('informacoes_comprador'), dict) else None,
                        'shipping_carrier': pedido_shopee.get('shipping_carrier'),
                        'ship_by_date': pedido_shopee.get('data_prevista_envio')
                    }
                
                # Extrair informacoes_comprador de forma segura
                informacoes_comprador = pedido_shopee.get('informacoes_comprador')
                if isinstance(informacoes_comprador, str):
                    try:
                        import json
                        informacoes_comprador = json.loads(informacoes_comprador)
                    except:
                        informacoes_comprador = {}
                elif not isinstance(informacoes_comprador, dict):
                    informacoes_comprador = {}
                
                order_data = {
                    'codigo_pedido_externo': pedido_shopee.get('codigo_pedido'),
                    'numero_pedido': pedido_shopee.get('codigo_pedido'),
                    'cliente_nome': informacoes_comprador.get('username') if informacoes_comprador else None,
                    'origem': 'SHOPEE',
                    'total_pedido': pedido_shopee.get('total_pedido', 0),
                    'is_flex': pedido_shopee.get('is_flex', False),
                    'data_limite_envio': pedido_shopee.get('data_prevista_envio'),
                    'servico_logistico': pedido_shopee.get('shipping_carrier'),
                    'buyer_username': informacoes_comprador.get('username') if informacoes_comprador else None,
                    'shipping_carrier': pedido_shopee.get('shipping_carrier')
                }
                
                # Mapear status Shopee para situacao_pedido_id
                status_map = {
                    'UNPAID': 1, 'READY_TO_SHIP': 2, 'PROCESSED': 3,
                    'SHIPPED': 5, 'COMPLETED': 6, 'IN_CANCEL': 7,
                    'CANCELLED': 7, 'INVOICED': 5
                }
                status_original = pedido_shopee.get('status')
                if status_original:
                    order_data['situacao_pedido_id'] = status_map.get(status_original, 1)
                
                order_service.upsert_order(
                    order_data=order_data,
                    platform='SHOPEE',
                    platform_order_id=pedido_shopee.get('codigo_pedido'),
                    raw_payload=raw_payload
                )
                
                success_count += 1
                if success_count % 100 == 0:
                    logger.info(f"Progresso: {success_count}/{len(new_orders)}")
                    
            except Exception as e:
                error_count += 1
                logger.error(f"Erro ao processar pedido {pedido_shopee.get('codigo_pedido')}: {e}")
        
        logger.info(f"✅ pedidos_shopee: {success_count} inseridos, {error_count} erros")
        return success_count
        
    except Exception as e:
        logger.error(f"Erro no backfill de pedidos_shopee: {e}")
        return 0


def main():
    logger.info("=" * 60)
    logger.info("INICIANDO BACKFILL DE PEDIDOS UNIFICADOS")
    logger.info("=" * 60)
    
    # 1. Buscar pedidos já existentes
    logger.info("Buscando pedidos já existentes em pedidos...")
    existing_codigo_externo, existing_numero_pedido = get_existing_pedidos()
    logger.info(f"Encontrados {len(existing_codigo_externo)} codigo_pedido_externo")
    logger.info(f"Encontrados {len(existing_numero_pedido)} numero_pedido")
    
    # 2. Backfill de pedidos_bling
    bling_count = backfill_from_pedidos_bling(existing_codigo_externo, existing_numero_pedido)
    
    # 3. Atualizar conjuntos existentes
    existing_codigo_externo, existing_numero_pedido = get_existing_pedidos()
    
    # 4. Backfill de pedidos_shopee
    shopee_count = backfill_from_pedidos_shopee(existing_codigo_externo, existing_numero_pedido)
    
    # 5. Resumo
    logger.info("=" * 60)
    logger.info("RESUMO DO BACKFILL:")
    logger.info(f"  pedidos_bling: {bling_count} pedidos inseridos")
    logger.info(f"  pedidos_shopee: {shopee_count} pedidos inseridos")
    logger.info(f"  Total: {bling_count + shopee_count} pedidos inseridos")
    logger.info("=" * 60)
    logger.info("Backfill concluído!")


if __name__ == "__main__":
    main()
