"""Integration administrators own intelligence collection settings."""
import logging
from flask import Blueprint, jsonify, request
from routes.auth import admin_required, require_request_permission
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.marketplace_insights_service import MarketplaceInsightsService, FINANCIAL

marketplace_insights_bp=Blueprint('marketplace_insights',__name__,url_prefix='/api/v2/marketplace/installed')


@marketplace_insights_bp.route('/<int:account_id>/insights',methods=['GET','PUT','POST'])
@admin_required
def insights(account_id):
    service=MarketplaceInsightsService(supabase_db)
    try:
        if request.method=='GET': return jsonify(success=True,data=service.read(account_id))
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict) or not isinstance(data.get('capability'),str):
            raise ValueError('Envie capacidade e ação em um objeto JSON.')
        capability=data.get('capability')
        if capability in FINANCIAL:
            denied=require_request_permission('gestao_financeiro','editar')
            if denied: return denied
        return jsonify(service.configure(account_id,capability,data.get('action'))),202
    except ValueError as exc:
        return jsonify(success=False,error=str(exc)),400
    except Exception as exc:
        logging.getLogger(__name__).error('Account insights unavailable: %s',type(exc).__name__)
        return jsonify(success=False,error='Dados de inteligência indisponíveis. Verifique a atualização do serviço.'),503
