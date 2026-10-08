"""Focused authorization and redaction contracts for the operations center."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask, session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402

with patch.object(supabase_db, "table", return_value=MagicMock()):
    from routes import auth, configuracoes, notifications, operations_api, task_center_api  # noqa: E402


class TestAccessControl(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-only"
        self.app.config["TESTING"] = True

    def test_forced_password_blocks_legacy_api_paths(self):
        with self.app.test_request_context(
            "/api/v1/legacy-data", headers={"Accept": "application/json"}
        ):
            session["must_change_password"] = True
            result = auth.require_password_change_before_api_access()

        response, status = result
        self.assertEqual(status, 403)
        self.assertEqual(response.get_json()["code"], "password_change_required")

    def test_forced_password_allows_password_change_and_profile_navigation(self):
        with self.app.test_request_context("/api/v2/change-password", method="POST"):
            session["must_change_password"] = True
            self.assertIsNone(auth.require_password_change_before_api_access())

        with self.app.test_request_context(
            "/perfil?trocar-senha=1", headers={"Accept": "text/html"}
        ):
            session["must_change_password"] = True
            self.assertIsNone(auth.require_password_change_before_api_access())

    def test_personal_center_uses_authenticated_identity_and_caps_page(self):
        self.app.register_blueprint(notifications.notifications_bp)
        authenticated_user = {"id": 17, "ativo": True, "is_admin": False}
        with patch.object(auth, "_active_session_user", return_value=authenticated_user), \
                patch.object(notifications, "get_current_user", return_value=authenticated_user), \
                patch.object(notifications.async_operation_service, "list_center", return_value={
                    "operations": [], "notifications": [], "unread_count": 0,
                    "pagination": {"operations_total": 0, "notifications_total": 0},
                }) as list_center:
            response = self.app.test_client().get(
                "/api/v2/notifications/center?user_id=99&limit=500&offset=-10"
            )

        self.assertEqual(response.status_code, 200)
        list_center.assert_called_once_with(17, limit=200, offset=0)

    def test_global_audit_requires_sector_permission(self):
        self.app.register_blueprint(operations_api.activity_api_bp)
        authenticated_user = {"id": 17, "ativo": True, "is_admin": False}
        with patch.object(auth, "_active_session_user", return_value=authenticated_user), \
                patch.object(auth.permissao_service, "has_permission", return_value=False):
            response = self.app.test_client().get("/api/v2/auditoria")

        self.assertEqual(response.status_code, 403)

    def test_operational_mode_cannot_be_changed_by_regular_user(self):
        self.app.register_blueprint(configuracoes.configuracoes_api_bp)
        operator = {"id": 17, "ativo": True, "is_admin": False}
        with patch.object(auth, "_active_session_user", return_value=operator), \
                patch.object(auth, "get_current_user", return_value=operator):
            response = self.app.test_client().post(
                "/api/v2/configuracoes/sistema",
                json={"database_operational_mode": "legacy"},
            )

        self.assertEqual(response.status_code, 403)

    def test_legacy_global_demand_permissions_cannot_be_written(self):
        self.app.register_blueprint(configuracoes.configuracoes_api_bp)
        operator = {"id": 17, "ativo": True, "is_admin": False}
        with patch.object(auth, "_active_session_user", return_value=operator):
            response = self.app.test_client().post(
                "/api/v2/configuracoes/demanda-permissions",
                json={"fields": {"administrativo": ["capas_produzidas_qtd"]}},
            )

        self.assertEqual(response.status_code, 403)

    def test_log_sanitizers_redact_nested_secrets_and_inline_tokens(self):
        payload = {
            "senha_hash": "must-not-leak",
            "details": "SUPABASE_SERVICE_ROLE_KEY=must-not-leak",
        }
        self.assertEqual(operations_api._sanitize(payload)["senha_hash"], "[redigido]")
        self.assertNotIn("must-not-leak", operations_api._sanitize(payload)["details"])
        self.assertEqual(task_center_api._sanitize({"partner_key": "must-not-leak"})["partner_key"], "[redigido]")


if __name__ == "__main__":
    unittest.main()
