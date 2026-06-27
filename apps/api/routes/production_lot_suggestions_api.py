from flask import jsonify, request, session

from routes.auth import login_required
from nistiprint_shared.services.production_lot_suggestions_service import (
    production_lot_suggestions_service,
)

from .demanda_producao_base import demanda_producao_api_bp


@demanda_producao_api_bp.route("/lote-suggestions", methods=["GET"])
@login_required
def list_lote_suggestions():
    try:
        payload = production_lot_suggestions_service.list_suggestions(
            search_term=request.args.get("search")
        )
        return jsonify({"success": True, **payload}), 200
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@demanda_producao_api_bp.route("/lote-suggestions/<path:suggestion_key>", methods=["GET"])
@login_required
def get_lote_suggestion_detail(suggestion_key):
    try:
        detail = production_lot_suggestions_service.get_suggestion_detail(suggestion_key)
        return jsonify({"success": True, "detail": detail}), 200
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 404
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@demanda_producao_api_bp.route("/lote-suggestions/confirm", methods=["POST"])
@login_required
def confirm_lote_suggestion():
    data = request.get_json(silent=True) or {}
    suggestion_key = data.get("suggestion_key")
    included_order_ids = data.get("included_order_ids") or []
    if not suggestion_key:
        return jsonify({"success": False, "message": "suggestion_key e obrigatorio."}), 400
    if not included_order_ids:
        return jsonify({"success": False, "message": "included_order_ids e obrigatorio."}), 400

    try:
        result = production_lot_suggestions_service.confirm_suggestion(
            suggestion_key,
            included_order_ids,
            user_id=session.get("user_email", "System"),
            nome_demanda=data.get("nome_demanda"),
            observacoes=data.get("observacoes"),
        )
        return jsonify(
            {
                "success": True,
                "message": "Demanda criada com sucesso.",
                "result": result,
            }
        ), 201
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "message": str(exc)}), 409
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500
