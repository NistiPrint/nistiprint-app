"""Focused authorization and redaction contracts for the operations center."""

import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask, session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402

with patch.object(supabase_db, "table", return_value=MagicMock()):
    from routes import auth, auditoria_estoque, configuracoes, estoque_api, notifications, operations_api, task_center_api  # noqa: E402


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

    def test_stock_audit_approval_requires_edit_permission(self):
        self.app.register_blueprint(auditoria_estoque.auditoria_estoque_bp)
        user = {"id": 17, "ativo": True, "is_admin": False}
        with patch.object(auth, "_active_session_user", return_value=user), \
                patch.object(auth.permissao_service, "has_permission", return_value=False), \
                patch.object(auditoria_estoque.auditoria_estoque_service, "aprovar_contagem") as approve:
            response = self.app.test_client().post("/api/v2/auditoria/123/aprovar")

        self.assertEqual(response.status_code, 403)
        approve.assert_not_called()

    def test_stock_audit_approval_uses_snapshot_and_stable_operation_identity(self):
        import importlib
        from types import SimpleNamespace
        from nistiprint_shared.database.database import db

        service_module = importlib.import_module(
            "nistiprint_shared.services.auditoria_estoque_service"
        )
        service = service_module.auditoria_estoque_service
        count = SimpleNamespace(
            id=123, produto_id=10, deposito_id=2, quantidade_contada=5,
            saldo_sistema_snapshot=4, observacao="contagem", status="PENDENTE",
            usuario_aprovador_id=None, data_processamento=None,
            to_dict=lambda: {"id": 123, "status": "APROVADO"},
        )
        actor = {"id": 17, "setor_id": 3, "setor_nome": "Corte"}
        with patch.object(service, "obter_contagem", return_value=count), \
                patch.object(service_module.estoque_service, "registrar_balanco") as balance, \
                patch.object(db.session, "commit"), patch.object(db.session, "rollback"):
            service.aprovar_contagem(123, 17, user_context=actor)

        kwargs = balance.call_args.kwargs
        self.assertEqual(kwargs["expected_saldo"], 4)
        self.assertEqual(kwargs["idempotency_key"], "auditoria-contagem:123")
        self.assertEqual(
            kwargs["operation_id"],
            str(uuid.uuid5(uuid.NAMESPACE_URL, "nistiprint:auditoria-contagem:123")),
        )
        self.assertEqual(kwargs["user_context"], actor)

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

    def test_home_operational_summary_requires_active_session(self):
        self.app.register_blueprint(task_center_api.task_center_bp)
        with patch.object(task_center_api, "_active_session_user", return_value=None), \
                patch.object(task_center_api.supabase_db, "table") as table:
            response = self.app.test_client().get("/api/v2/home/operational-summary")

        self.assertEqual(response.status_code, 401)
        table.assert_not_called()

    def test_home_operational_summary_omits_sections_without_permission(self):
        self.app.register_blueprint(task_center_api.task_center_bp)
        user = {"id": 17, "ativo": True, "is_admin": False}
        with patch.object(task_center_api, "_active_session_user", return_value=user), \
                patch.object(task_center_api, "user_has_permission", return_value=False), \
                patch.object(task_center_api.supabase_db, "table") as table:
            response = self.app.test_client().get("/api/v2/home/operational-summary")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["sections"], {})
        table.assert_not_called()

    def test_home_operational_summary_returns_counts_only_for_authorized_sections(self):
        self.app.register_blueprint(task_center_api.task_center_bp)
        user = {"id": 17, "ativo": True, "is_admin": False}
        counts = {
            "webhook_events": 4,
            "pending_order_reconciliations": 2,
            "itens_demanda": 3,
            "impressao_capas_envios": 1,
            "estoque_operacoes": 0,
            "estoque_eventos_outbox": 5,
            "v_estoque_saldo_ledger_divergencias": 6,
        }

        class Query:
            def __init__(self, table_name):
                self.table_name = table_name
                self.count = counts[table_name]

            def select(self, *_args, **_kwargs):
                return self

            def execute(self):
                return self

            @property
            def not_(self):
                return self

            def __getattr__(self, _name):
                return lambda *_args, **_kwargs: self

        def permission(_user, resource, action):
            return action == "ler" and resource in {"vendas", "demanda_producao", "producao", "estoque"}

        with patch.object(task_center_api, "_active_session_user", return_value=user), \
                patch.object(task_center_api, "user_has_permission", side_effect=permission), \
                patch.object(task_center_api.supabase_db, "table", side_effect=lambda name: Query(name)):
            response = self.app.test_client().get("/api/v2/home/operational-summary")

        self.assertEqual(response.status_code, 200)
        sections = response.get_json()["sections"]
        self.assertEqual(set(sections), {"orders", "production", "printing", "inventory"})
        self.assertEqual(sections["orders"]["webhook_attention"], 4)
        self.assertEqual(sections["orders"]["order_reconciliation_open"], 2)
        self.assertEqual(sections["production"]["items_with_processing_error"], 3)
        self.assertEqual(sections["printing"]["unresolved_sends"], 1)
        self.assertEqual(sections["inventory"]["outbox_pending"], 5)
        self.assertEqual(sections["inventory"]["balance_divergences"], 6)

    def test_stock_ledger_divergence_list_requires_stock_permission(self):
        self.app.register_blueprint(estoque_api.estoque_api_bp, url_prefix="/api/v2/estoque")
        user = {"id": 17, "ativo": True, "is_admin": False}
        with patch.object(auth, "_active_session_user", return_value=user), \
                patch.object(auth, "user_has_permission", return_value=False), \
                patch.object(estoque_api.supabase_db, "table") as table:
            response = self.app.test_client().get("/api/v2/estoque/divergencias-ledger")

        self.assertEqual(response.status_code, 403)
        table.assert_not_called()

    def test_legacy_stock_batch_requires_operation_identity(self):
        self.app.register_blueprint(estoque_api.estoque_api_bp, url_prefix="/api/v2/estoque")
        user = {"id": 17, "ativo": True, "is_admin": False, "setor_id": 3, "setor_nome": "Corte"}
        with patch.object(auth, "_active_session_user", return_value=user), \
                patch.object(auth.permissao_service, "has_permission", return_value=True), \
                patch.object(estoque_api, "get_current_user", return_value=user), \
                patch.object(estoque_api.estoque_service, "registrar_movimentacao_lote") as registrar:
            response = self.app.test_client().post(
                "/api/v2/estoque/movimentar-lote",
                json={"movimentacoes": [{"produto_id": 10, "quantidade": 1, "tipo_movimento": "ENTRADA"}]},
            )

        self.assertEqual(response.status_code, 400)
        registrar.assert_not_called()

    def test_legacy_stock_batch_passes_stable_operation_and_server_owned_source(self):
        self.app.register_blueprint(estoque_api.estoque_api_bp, url_prefix="/api/v2/estoque")
        user = {"id": 17, "ativo": True, "is_admin": False, "setor_id": 3, "setor_nome": "Corte"}
        operation_id = "00000000-0000-4000-8000-000000000043"
        result = {"operation_id": operation_id, "status": "CONFIRMADO", "movimentos": [{"id": 1}]}
        with patch.object(auth, "_active_session_user", return_value=user), \
                patch.object(auth.permissao_service, "has_permission", return_value=True), \
                patch.object(estoque_api, "get_current_user", return_value=user), \
                patch.object(estoque_api.estoque_service, "registrar_movimentacao_lote", return_value=result) as registrar:
            response = self.app.test_client().post(
                "/api/v2/estoque/movimentar-lote",
                json={
                    "operation_id": operation_id,
                    "movimentacoes": [{"produto_id": 10, "quantidade": 1, "tipo_movimento": "ENTRADA"}],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["operation_id"], operation_id)
        self.assertEqual(response.get_json()["falhas"], 0)
        kwargs = registrar.call_args.kwargs
        self.assertEqual(kwargs["operation_id"], operation_id)
        self.assertEqual(kwargs["source"], {
            "source_type": "MOVIMENTACAO_LOTE_MANUAL",
            "source_id": operation_id,
        })

    def test_stock_reversal_requires_authentication_and_fails_closed(self):
        self.app.register_blueprint(estoque_api.estoque_api_bp, url_prefix="/api/v2/estoque")
        user = {"id": 17, "ativo": True, "is_admin": False}
        with patch.object(auth, "_active_session_user", return_value=None):
            unauthenticated = self.app.test_client().post(
                "/api/v2/estoque/reverter-movimentacao",
                json={"lancamento_id": 501},
            )
        self.assertEqual(unauthenticated.status_code, 401)

        with patch.object(auth, "_active_session_user", return_value=user), \
                patch.object(auth.permissao_service, "has_permission", return_value=True), \
                patch.object(estoque_api.estoque_service, "reverter_movimentacao", create=True) as reverse:
            response = self.app.test_client().post(
                "/api/v2/estoque/reverter-movimentacao",
                json={"lancamento_id": 501},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "compensation_unavailable")
        reverse.assert_not_called()

    def test_stock_batch_balance_route_uses_shared_service_contract(self):
        self.app.register_blueprint(estoque_api.estoque_api_bp, url_prefix="/api/v2/estoque")
        user = {"id": 17, "ativo": True, "is_admin": False}
        balances = {"10": {"quantidade": 3, "quantidade_disponivel": 3}}
        with patch.object(auth, "_active_session_user", return_value=user), \
                patch.object(auth.permissao_service, "has_permission", return_value=True), \
                patch.object(estoque_api.estoque_service, "get_saldos_em_lote", return_value=balances) as get_balances:
            response = self.app.test_client().post(
                "/api/v2/estoque/saldos-batch",
                json={"product_ids": [10], "deposito_id": 2},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), balances)
        get_balances.assert_called_once_with([10], 2)

    def test_product_search_reads_quantities_from_batch_balance_contract(self):
        self.app.register_blueprint(estoque_api.estoque_api_bp, url_prefix="/api/v2/estoque")
        user = {"id": 17, "ativo": True, "is_admin": False}
        products = [{"id": 10, "sku": "P-10", "nome": "Produto dez"}]
        balances = {"10": {"quantidade": 7, "quantidade_disponivel": 6}}
        with patch.object(auth, "_active_session_user", return_value=user), \
                patch.object(auth.permissao_service, "has_permission", return_value=True), \
                patch.object(estoque_api.product_service, "search_produtos", return_value=products), \
                patch.object(estoque_api.estoque_service, "get_saldos_em_lote", return_value=balances) as get_balances:
            response = self.app.test_client().get("/api/v2/estoque/produtos-busca?deposito_id=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["saldo"], 7)
        get_balances.assert_called_once_with([10], "2")

    def test_stock_ledger_divergence_list_pages_and_caps_result_size(self):
        self.app.register_blueprint(estoque_api.estoque_api_bp, url_prefix="/api/v2/estoque")
        user = {"id": 17, "ativo": True, "is_admin": False}

        class Query:
            def __init__(self):
                self.count = 1
                self.range_args = None

            def select(self, *_args, **_kwargs):
                return self

            def order(self, *_args, **_kwargs):
                return self

            def range(self, start, end):
                self.range_args = (start, end)
                return self

            def execute(self):
                self.data = [{"produto_id": 5, "deposito_id": 1, "diferenca": 2}]
                return self

        query = Query()
        with patch.object(auth, "_active_session_user", return_value=user), \
                patch.object(auth, "user_has_permission", return_value=True), \
                patch.object(estoque_api.supabase_db, "table", return_value=query):
            response = self.app.test_client().get(
                "/api/v2/estoque/divergencias-ledger?limit=500&offset=50"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(query.range_args, (50, 149))
        self.assertEqual(response.get_json()["limit"], 100)
        self.assertEqual(response.get_json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
