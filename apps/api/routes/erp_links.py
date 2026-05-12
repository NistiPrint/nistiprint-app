"""
Endpoints para gerenciamento de vínculos ERP ↔ Marketplace.

Permite configurar quais marketplaces estão vinculados a cada instância de ERP (Bling),
e qual loja Bling (loja_id) corresponde a cada marketplace.
"""

from flask import Blueprint, request, jsonify
from nistiprint_shared.services.erp_marketplace_links_service import (
    erp_marketplace_links_service
)
from utils.api_response import ApiResponse
import logging

logger = logging.getLogger("ErpLinksAPI")

erp_links_bp = Blueprint('erp_links', __name__, url_prefix='/api/v2/erp-links')


@erp_links_bp.route('/erp/<erp_integration_id>/links', methods=['GET'])
def get_erp_links(erp_integration_id):
    """
    Retorna todos vínculos de um ERP.

    Query params:
        include_inactive: bool (opcional) - Incluir links inativos

    Response:
        {
            "success": true,
            "data": [
                {
                    "id": "uuid",
                    "erp_integration_id": 1,
                    "marketplace_integration_id": 2,
                    "erp_store_id": "204047801",
                    "store_name": "Shopee Antiga",
                    "config": {"id_campo_personalizado": 2797770},
                    "marketplace": {
                        "id": 2,
                        "module_id": "shopee",
                        "instance_name": "Shopee - CNPJ X"
                    }
                }
            ]
        }
    """
    try:
        links = erp_marketplace_links_service.get_links_by_erp(int(erp_integration_id))
        return ApiResponse.success(data=links)
    except Exception as e:
        logger.error(f"Erro ao buscar vínculos: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@erp_links_bp.route('/erp/<erp_integration_id>/links', methods=['POST'])
def create_erp_link(erp_integration_id):
    """
    Cria novo vínculo ERP ↔ Marketplace.

    Payload:
        {
            "marketplace_integration_id": 2,
            "erp_store_id": "204047801",
            "store_name": "Shopee Antiga",  // opcional
            "config": {  // opcional
                "id_campo_personalizado": 2797770
            }
        }

    Response:
        {
            "success": true,
            "data": { ... vínculo criado ... }
        }
    """
    try:
        data = request.get_json()

        if not data:
            return ApiResponse.error(message="Payload é obrigatório", status_code=400)

        marketplace_integration_id = data.get('marketplace_integration_id')
        marketplace_module_id = data.get('marketplace_module_id')
        erp_store_id = data.get('erp_store_id')
        store_name = data.get('store_name')
        config = data.get('config', {})

        if not erp_store_id or not (marketplace_integration_id or marketplace_module_id):
            return ApiResponse.error(
                message="marketplace_integration_id e erp_store_id são obrigatórios",
                status_code=400
            )

        link = erp_marketplace_links_service.create_link(
            erp_integration_id=int(erp_integration_id),
            marketplace_integration_id=int(marketplace_integration_id) if marketplace_integration_id else None,
            marketplace_module_id=marketplace_module_id,
            erp_store_id=str(erp_store_id),
            store_name=store_name,
            config=config
        )

        if link:
            return ApiResponse.success(data=link, status_code=201)
        else:
            return ApiResponse.error(
                message="Falha ao criar vínculo. Verifique se os IDs existem.",
                status_code=400
            )

    except Exception as e:
        logger.error(f"Erro ao criar vínculo: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@erp_links_bp.route('/links/<link_id>', methods=['DELETE'])
def delete_erp_link(link_id):
    """
    Remove vínculo ERP ↔ Marketplace.

    Response:
        {
            "success": true,
            "message": "Vínculo removido com sucesso"
        }
    """
    try:
        success = erp_marketplace_links_service.delete_link(link_id)

        if success:
            return ApiResponse.success(message="Vínculo removido com sucesso")
        else:
            return ApiResponse.error(
                message="Vínculo não encontrado",
                status_code=404
            )

    except Exception as e:
        logger.error(f"Erro ao remover vínculo: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@erp_links_bp.route('/links/<link_id>/config', methods=['PUT'])
def update_erp_link_config(link_id):
    """
    Atualiza configurações de um vínculo.

    Payload:
        {
            "id_campo_personalizado": 2797770
        }

    Response:
        {
            "success": true,
            "data": { ... vínculo atualizado ... }
        }
    """
    try:
        data = request.get_json()

        if not data:
            return ApiResponse.error(message="Payload é obrigatório", status_code=400)

        link = erp_marketplace_links_service.update_config(link_id, data)

        if link:
            return ApiResponse.success(data=link)
        else:
            return ApiResponse.error(
                message="Vínculo não encontrado",
                status_code=404
            )

    except Exception as e:
        logger.error(f"Erro ao atualizar config: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@erp_links_bp.route('/lookup/bling-integration/<store_id>', methods=['GET'])
def lookup_bling_integration(store_id):
    """
    Dado store_id (loja Bling), retorna bling_integration_id.

    Usa índice em channel_connections para lookup rápido.

    Response:
        {
            "success": true,
            "data": {
                "bling_integration_id": 1,
                "store_id": "204047801"
            }
        }
    """
    try:
        from nistiprint_shared.database.supabase_db_service import supabase_db

        result = supabase_db.table('channel_connections') \
            .select('bling_integration_id, aggregator_store_id') \
            .eq('aggregator_store_id', str(store_id)) \
            .eq('is_active', True) \
            .execute()

        if result.data:
            return ApiResponse.success(data={
                'bling_integration_id': result.data[0]['bling_integration_id'],
                'store_id': store_id
            })
        else:
            return ApiResponse.error(
                message=f"Loja Bling {store_id} não encontrada",
                status_code=404
            )

    except Exception as e:
        logger.error(f"Erro ao lookup bling_integration: {e}")
        return ApiResponse.error(message=str(e), status_code=500)


@erp_links_bp.route('/marketplace/<marketplace_integration_id>/links', methods=['GET'])
def get_marketplace_links(marketplace_integration_id):
    """
    Retorna todos ERPs vinculados a um marketplace.

    Response:
        {
            "success": true,
            "data": [
                {
                    "id": "uuid",
                    "erp_integration_id": 1,
                    "marketplace_integration_id": 2,
                    "erp_store_id": "204047801",
                    "store_name": "Shopee Antiga",
                    "erp": {
                        "id": 1,
                        "module_id": "bling",
                        "instance_name": "Bling - Conta 01"
                    }
                }
            ]
        }
    """
    try:
        links = erp_marketplace_links_service.get_links_by_marketplace(
            int(marketplace_integration_id)
        )
        return ApiResponse.success(data=links)
    except Exception as e:
        logger.error(f"Erro ao buscar vínculos: {e}")
        return ApiResponse.error(message=str(e), status_code=500)
