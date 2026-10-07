"""Unified admin API for AI personalization settings by connected account."""
from flask import Blueprint, request, session

from nistiprint_shared.services import ai_personalization_account_config as service
from routes.auth import admin_required

ai_personalization_config_bp = Blueprint("ai_personalization_config", __name__)


@ai_personalization_config_bp.get("/api/v2/ai-personalization/accounts")
@admin_required
def list_accounts():
    try:
        return {"success": True, "accounts": service.list_accounts()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}, 500


@ai_personalization_config_bp.get("/api/v2/ai-personalization/accounts/<int:integration_id>/config")
@admin_required
def get_account_config(integration_id):
    try:
        account = service.account_context(integration_id)
        return {"success": True, "account": account, "config": service.get_config(integration_id)}
    except LookupError as exc:
        return {"success": False, "error": str(exc)}, 404
    except (ValueError, TypeError) as exc:
        return {"success": False, "error": str(exc)}, 400
    except Exception as exc:
        return {"success": False, "error": str(exc)}, 500


@ai_personalization_config_bp.put("/api/v2/ai-personalization/accounts/<int:integration_id>/config")
@admin_required
def update_account_config(integration_id):
    try:
        config = service.update_config(integration_id, request.get_json(silent=True) or {}, user_id=session.get("user_id"))
        return {"success": True, "config": config, "message": "Configuração salva para esta conta."}
    except LookupError as exc:
        return {"success": False, "error": str(exc)}, 404
    except (ValueError, TypeError) as exc:
        return {"success": False, "error": str(exc)}, 400
    except Exception as exc:
        return {"success": False, "error": "Não foi possível salvar a configuração."}, 500


@ai_personalization_config_bp.post("/api/v2/ai-personalization/accounts/<int:integration_id>/preview")
@admin_required
def preview_account_config(integration_id):
    try:
        return {"success": True, "result": service.preview_config(integration_id, request.get_json(silent=True) or {})}
    except LookupError as exc:
        return {"success": False, "error": str(exc)}, 404
    except (ValueError, TypeError) as exc:
        return {"success": False, "error": str(exc)}, 400
    except Exception:
        return {"success": False, "error": "Não foi possível testar o prompt desta conta."}, 500
