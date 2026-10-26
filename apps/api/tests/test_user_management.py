"""Contracts for administrative user lifecycle routes and safeguards."""

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nistiprint_shared.database.database import db  # noqa: E402
from nistiprint_shared.database.supabase_db_service import DatabaseMode, supabase_db  # noqa: E402

supabase_auth = MagicMock()


@contextmanager
def mocked_supabase_auth_module():
    module = ModuleType("nistiprint_shared.services.supabase_auth_service")
    module.supabase_auth = supabase_auth
    with patch.dict(sys.modules, {"nistiprint_shared.services.supabase_auth_service": module}):
        yield

with patch.object(supabase_db, "table", return_value=MagicMock()):
    from routes import auth  # noqa: E402
    from routes import usuarios_setores as user_routes  # noqa: E402

from nistiprint_shared.models.usuario import Usuario  # noqa: E402
from nistiprint_shared.models.setor import Setor  # noqa: E402
from nistiprint_shared.services.usuario_service import UsuarioService  # noqa: E402


class TestUserManagement(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-only"
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        db.init_app(self.app)
        self.app.register_blueprint(user_routes.usuarios_setores_api_bp)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def admin(self):
        return patch.object(auth, "_active_session_user", return_value={"id": 1, "ativo": True, "is_admin": True})

    def test_user_routes_require_admin(self):
        with patch.object(auth, "_active_session_user", return_value=None):
            response = self.client.get("/api/v2/usuarios-setores/usuario")
        self.assertEqual(response.status_code, 401)

    def test_supabase_user_creation_inserts_only_columns_and_requires_confirmed_row(self):
        setor_query = MagicMock()
        setor_query.filter_by.return_value.first.return_value = SimpleNamespace(id=3, ativo=True)
        inserted = {"id": 12}
        with patch("nistiprint_shared.services.usuario_service.get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(Setor, "query", setor_query), \
                patch.object(UsuarioService, "_matching_email_ids", return_value=[]), \
                patch.object(supabase_db, "insert", return_value=inserted) as insert, \
                patch.object(Usuario, "to_dict_without_password", autospec=True, return_value={"id": 12}):
            result = UsuarioService().create({
                "nome": "Pessoa", "email": " person@example.com ", "setor_id": 3,
                "senha": "temporary-123", "is_admin": False, "must_change_password": True,
            })
        self.assertEqual(result["id"], 12)
        table_name, record = insert.call_args.args
        self.assertEqual(table_name, "usuarios")
        self.assertEqual(set(record), {
            "nome", "email", "senha_hash", "setor_id", "ativo", "is_admin",
            "must_change_password", "session_version",
        })
        self.assertEqual(record["email"], "person@example.com")
        self.assertTrue(insert.call_args.kwargs["raise_on_error"])

        with patch("nistiprint_shared.services.usuario_service.get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(Setor, "query", setor_query), \
                patch.object(UsuarioService, "_matching_email_ids", return_value=[]), \
                patch.object(supabase_db, "insert", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "não confirmou a gravação"):
                UsuarioService().create({
                    "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                    "senha": "temporary-123", "is_admin": False,
                })

    def test_supabase_user_list_keeps_pending_users_visible_and_surfaces_query_errors(self):
        row = {"id": 12, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
               "ativo": True, "is_admin": False, "auth_user_id": None,
               "must_change_password": True, "senha_hash": "must-not-leak"}
        service = UsuarioService()
        with patch("nistiprint_shared.services.usuario_service.get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(supabase_db, "get_all", return_value=[row]) as get_all, \
                patch.object(service, "_populate_setor_nomes"):
            users = service.get_all()
        get_all.assert_called_once_with("usuarios", raise_on_error=True)
        self.assertEqual(users[0]["id"], 12)
        self.assertNotIn("senha_hash", users[0])
        with patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE):
            self.assertEqual(user_routes._with_access_status(users[0])["access_status"], "pending")

        with patch("nistiprint_shared.services.usuario_service.get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(supabase_db, "get_all", side_effect=RuntimeError("database unavailable")):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                service.get_all()

    def test_user_creation_does_not_provision_auth_if_database_insert_fails(self):
        payload = {"nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "senha": "temporary-123", "is_admin": False}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(user_routes.usuario_service, "validate_create", return_value="person@example.com"), \
                patch.object(supabase_auth, "find_user_by_email", return_value=None), \
                patch.object(user_routes.usuario_service, "create", side_effect=RuntimeError("Insert failed")), \
                patch.object(user_routes, "_create_auth_user") as create_auth:
            response = self.client.post("/api/v2/usuarios-setores/usuario", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Insert failed", response.get_json()["error"])
        create_auth.assert_not_called()

    def test_auth_only_identity_is_recovered_into_local_user_without_deleting_auth(self):
        payload = {"nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "senha": "temporary-123", "is_admin": False}
        identity = SimpleNamespace(id="auth-existing")
        linked_user = {"id": 12, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                       "ativo": True, "is_admin": False, "auth_user_id": "auth-existing",
                       "must_change_password": True}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(user_routes.usuario_service, "validate_create", return_value="person@example.com"), \
                patch.object(supabase_auth, "find_user_by_email", return_value=identity), \
                patch.object(supabase_auth, "update_user", return_value=identity) as update_auth, \
                patch.object(supabase_auth, "authenticate", return_value={"id": "auth-existing"}) as authenticate, \
                patch.object(user_routes.usuario_service, "create", return_value=linked_user) as create_user, \
                patch.object(user_routes, "_create_auth_user") as create_auth, \
                patch.object(supabase_auth, "delete_user") as delete_auth, \
                patch.object(user_routes, "_audit"):
            response = self.client.post("/api/v2/usuarios-setores/usuario", json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertIn("recuperado", response.get_json()["message"])
        self.assertEqual(response.get_json()["usuario"]["access_status"], "password_change_required")
        self.assertEqual(create_user.call_args.args[0]["auth_user_id"], "auth-existing")
        update_auth.assert_called_once_with("auth-existing", {
            "password": "temporary-123", "email_confirm": True, "user_metadata": {"name": "Pessoa"},
        })
        authenticate.assert_called_once_with("person@example.com", "temporary-123")
        create_auth.assert_not_called()
        delete_auth.assert_not_called()

    def test_existing_operational_email_is_reported_as_duplicate(self):
        payload = {"nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "senha": "temporary-123", "is_admin": False}
        with self.admin(), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(user_routes.usuario_service, "validate_create", side_effect=ValueError("Usuário com email já existe")), \
                patch.object(user_routes.usuario_service, "create") as create_user:
            response = self.client.post("/api/v2/usuarios-setores/usuario", json=payload)
        self.assertEqual(response.status_code, 409)
        self.assertIn("já existe", response.get_json()["error"])
        create_user.assert_not_called()

    def test_auth_created_but_local_link_failed_remains_pending_and_recoverable(self):
        payload = {"nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "senha": "temporary-123", "is_admin": False}
        created_user = {"id": 12, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                        "ativo": True, "is_admin": False, "auth_user_id": None,
                        "must_change_password": True}
        auth_identity = SimpleNamespace(id="auth-12")
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(user_routes.usuario_service, "validate_create", return_value="person@example.com"), \
                patch.object(supabase_auth, "find_user_by_email", return_value=None), \
                patch.object(user_routes.usuario_service, "create", return_value=created_user), \
                patch.object(user_routes, "_create_auth_user", return_value=auth_identity), \
                patch.object(supabase_auth, "update_user", return_value=auth_identity), \
                patch.object(supabase_auth, "authenticate", return_value={"id": "auth-12"}), \
                patch.object(user_routes.usuario_service, "update", side_effect=RuntimeError("link failed")), \
                patch.object(supabase_auth, "delete_user") as delete_auth, \
                patch.object(user_routes, "_audit"):
            response = self.client.post("/api/v2/usuarios-setores/usuario", json=payload)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["usuario"]["access_status"], "pending")
        self.assertEqual(response.get_json()["usuario"]["id"], 12)
        delete_auth.assert_not_called()

    def test_invalid_duplicate_or_inactive_sector_is_rejected_before_auth_email_update(self):
        current = {"id": 2, "nome": "Pessoa", "email": "old@example.com", "setor_id": 4,
                   "ativo": True, "is_admin": False, "auth_user_id": "auth-2", "session_version": 0}
        payload = {"nome": "Pessoa", "email": "new@example.com", "setor_id": "9", "ativo": True, "is_admin": False}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.usuario_service, "validate_update", side_effect=ValueError("E-mail duplicado ou setor inativo.")), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(supabase_auth, "update_user") as update_auth:
            response = self.client.put("/api/v2/usuarios-setores/usuario/2", json=payload)
        self.assertEqual(response.status_code, 400)
        update_auth.assert_not_called()

    def test_default_admin_cannot_be_renamed_or_demoted(self):
        current = {"id": 1, "nome": "Admin", "email": "admin@admin.com", "setor_id": 1,
                   "ativo": True, "is_admin": True, "auth_user_id": "auth-1", "session_version": 0}
        payload = {"nome": "Admin", "email": "other@example.com", "setor_id": "1", "ativo": True, "is_admin": False}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(supabase_auth, "update_user") as update_auth:
            response = self.client.put("/api/v2/usuarios-setores/usuario/1", json=payload)
        self.assertEqual(response.status_code, 400)
        update_auth.assert_not_called()

    def test_last_admin_cannot_be_deactivated(self):
        user = SimpleNamespace(id=7, email="admin2@example.com", ativo=True, is_admin=True, session_version=4)
        query = MagicMock()
        query.filter_by.return_value.first.return_value = user
        with patch.object(Usuario, "query", query), \
                patch.object(UsuarioService, "_active_admin_count", return_value=1), \
                patch.object(db.session, "commit") as commit:
            with self.assertRaisesRegex(ValueError, "último administrador"):
                UsuarioService().delete(7)
        self.assertTrue(user.ativo)
        self.assertEqual(user.session_version, 4)
        commit.assert_not_called()

    def test_default_admin_cannot_be_deactivated(self):
        user = SimpleNamespace(id=1, email="admin@admin.com", ativo=True, is_admin=True, session_version=0)
        query = MagicMock()
        query.filter_by.return_value.first.return_value = user
        with patch.object(Usuario, "query", query), patch.object(db.session, "commit") as commit:
            with self.assertRaisesRegex(ValueError, "conta administrativa padrão"):
                UsuarioService().delete(1)
        self.assertTrue(user.ativo)
        commit.assert_not_called()

    def test_deactivation_revokes_sessions_and_keeps_account_record(self):
        user = SimpleNamespace(id=7, email="person@example.com", ativo=True, is_admin=False, session_version=4)
        query = MagicMock()
        query.filter_by.return_value.first.return_value = user
        with patch.object(Usuario, "query", query), patch.object(db.session, "commit"):
            self.assertTrue(UsuarioService().delete(7))
        self.assertFalse(user.ativo)
        self.assertEqual(user.session_version, 5)

    def test_update_validation_rejects_duplicate_email(self):
        current = SimpleNamespace(id=2, email="old@example.com", ativo=True, is_admin=False, setor_id=4)
        query = MagicMock()
        query.filter_by.return_value.first.return_value = current
        with patch.object(Usuario, "query", query), \
                patch.object(UsuarioService, "_matching_email_ids", return_value=[2, 9]):
            with self.assertRaisesRegex(ValueError, "já existe"):
                UsuarioService().validate_update(2, {"email": "duplicate@example.com"})

    def test_update_validation_rejects_changed_inactive_sector(self):
        current = SimpleNamespace(id=2, email="user@example.com", ativo=True, is_admin=False, setor_id=4)
        user_query = MagicMock()
        user_query.filter_by.return_value.first.return_value = current
        sector_query = MagicMock()
        sector_query.filter_by.return_value.first.return_value = None
        with patch.object(Usuario, "query", user_query), \
                patch("nistiprint_shared.services.usuario_service.Setor.query", sector_query), \
                patch.object(UsuarioService, "_matching_email_ids", return_value=[2]):
            with self.assertRaisesRegex(ValueError, "Setor.*não encontrado"):
                UsuarioService().validate_update(2, {"email": "user@example.com", "setor_id": 9})

    def test_inactive_account_cannot_be_reactivated_without_a_temporary_password(self):
        current = {"id": 7, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "ativo": False, "is_admin": False, "auth_user_id": None, "session_version": 2}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.setor_service, "get_by_id", return_value={"id": 3, "ativo": True}), \
                patch.object(user_routes.usuario_service, "email_belongs_uniquely_to", return_value=True), \
                patch.object(user_routes.usuario_service, "update") as update_user:
            response = self.client.post("/api/v2/usuarios-setores/usuario/7/reactivate", json={"senha_inicial": "short"})
        self.assertEqual(response.status_code, 400)
        update_user.assert_not_called()

    def test_account_with_inactive_sector_cannot_be_reactivated(self):
        current = {"id": 7, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "ativo": False, "is_admin": False, "auth_user_id": "auth-7", "session_version": 2}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.setor_service, "get_by_id", return_value=None), \
                patch.object(user_routes.usuario_service, "update") as update_user, \
                patch.object(supabase_auth, "update_user") as update_auth:
            response = self.client.post("/api/v2/usuarios-setores/usuario/7/reactivate", json={"senha_inicial": "temporary-123"})
        self.assertEqual(response.status_code, 409)
        update_user.assert_not_called()
        update_auth.assert_not_called()

    def test_reactivation_sets_password_change_and_invalidates_old_sessions(self):
        current = {"id": 7, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "ativo": False, "is_admin": False, "auth_user_id": "auth-7", "session_version": 2,
                   "must_change_password": False}
        updated = {**current, "ativo": True, "session_version": 3, "must_change_password": True}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.setor_service, "get_by_id", return_value={"id": 3, "ativo": True}), \
                patch.object(user_routes.usuario_service, "email_belongs_uniquely_to", return_value=True), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(supabase_auth, "update_user", return_value=SimpleNamespace(id="auth-7")) as update_auth, \
                patch.object(supabase_auth, "authenticate", return_value={"id": "auth-7"}) as authenticate, \
                patch.object(user_routes.usuario_service, "update", return_value=updated) as update_user, \
                patch.object(user_routes, "_audit"):
            response = self.client.post("/api/v2/usuarios-setores/usuario/7/reactivate", json={"senha_inicial": "temporary-123"})
        self.assertEqual(response.status_code, 200)
        update_auth.assert_called_once_with("auth-7", {"password": "temporary-123"})
        authenticate.assert_called_once_with("person@example.com", "temporary-123")
        changes = update_user.call_args.args[1]
        self.assertTrue(changes["ativo"])
        self.assertTrue(changes["must_change_password"])
        self.assertEqual(changes["session_version"], 3)

    def test_local_mode_reactivation_updates_password_and_forces_change(self):
        current = {"id": 7, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "ativo": False, "is_admin": False, "auth_user_id": None, "session_version": 2}
        updated = {**current, "ativo": True, "session_version": 3, "must_change_password": True}
        with self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.setor_service, "get_by_id", return_value={"id": 3, "ativo": True}), \
                patch.object(user_routes.usuario_service, "email_belongs_uniquely_to", return_value=True), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.MYSQL), \
                patch.object(user_routes.usuario_service, "update", return_value=updated) as update_user, \
                patch.object(user_routes, "_audit"):
            response = self.client.post("/api/v2/usuarios-setores/usuario/7/reactivate", json={"senha_inicial": "temporary-123"})
        self.assertEqual(response.status_code, 200)
        changes = update_user.call_args.args[1]
        self.assertEqual(changes["senha"], "temporary-123")
        self.assertTrue(changes["ativo"])
        self.assertTrue(changes["must_change_password"])
        self.assertEqual(changes["session_version"], 3)

    def test_auth_reset_failure_returns_error_and_leaves_forced_change_state(self):
        current = {"id": 7, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "ativo": True, "is_admin": False, "auth_user_id": "auth-7", "session_version": 2,
                   "must_change_password": False}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.usuario_service, "email_belongs_uniquely_to", return_value=True), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(supabase_auth, "update_user", side_effect=RuntimeError("Auth unavailable")), \
                patch.object(user_routes.usuario_service, "update", return_value={**current, "session_version": 3, "must_change_password": True}) as update_user:
            response = self.client.post("/api/v2/usuarios-setores/usuario/7/access", json={"senha_inicial": "temporary-123"})
        self.assertEqual(response.status_code, 502)
        self.assertTrue(update_user.call_args.args[1]["must_change_password"])
        self.assertEqual(update_user.call_args.args[1]["session_version"], 3)

    def test_auth_reset_is_not_reported_success_when_new_password_cannot_authenticate(self):
        current = {"id": 7, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "ativo": True, "is_admin": False, "auth_user_id": "auth-7", "session_version": 2,
                   "must_change_password": False}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.usuario_service, "email_belongs_uniquely_to", return_value=True), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(supabase_auth, "update_user", return_value=SimpleNamespace(id="auth-7")), \
                patch.object(supabase_auth, "authenticate", return_value=None) as authenticate, \
                patch.object(user_routes.usuario_service, "update", return_value={
                    **current, "session_version": 3, "must_change_password": True,
                }), \
                patch.object(user_routes, "_audit") as audit:
            response = self.client.post("/api/v2/usuarios-setores/usuario/7/access", json={"senha_inicial": "temporary-123"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("atualizar a senha", response.get_json()["error"].lower())
        authenticate.assert_called_once_with("person@example.com", "temporary-123")
        audit.assert_not_called()

    def test_linked_auth_identity_reset_returns_updated_user(self):
        current = {"id": 7, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "ativo": True, "is_admin": False, "auth_user_id": "auth-7", "session_version": 2,
                   "must_change_password": False}
        updated = {**current, "session_version": 3, "must_change_password": True}
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.usuario_service, "email_belongs_uniquely_to", return_value=True), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(supabase_auth, "update_user", return_value=SimpleNamespace(id="auth-7")) as update_auth, \
                patch.object(supabase_auth, "authenticate", return_value={"id": "auth-7"}) as authenticate, \
                patch.object(user_routes.usuario_service, "update", return_value=updated) as update_user, \
                patch.object(user_routes, "_audit"):
            response = self.client.post("/api/v2/usuarios-setores/usuario/7/access", json={"senha_inicial": "temporary-123"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["usuario"]["access_status"], "password_change_required")
        self.assertEqual(response.get_json()["usuario"]["session_version"], 3)
        update_auth.assert_called_once_with("auth-7", {"password": "temporary-123"})
        authenticate.assert_called_once_with("person@example.com", "temporary-123")
        self.assertEqual(update_user.call_count, 1)

    def test_existing_auth_identity_is_not_deleted_when_local_link_fails(self):
        current = {"id": 7, "nome": "Pessoa", "email": "person@example.com", "setor_id": 3,
                   "ativo": True, "is_admin": False, "auth_user_id": None, "session_version": 2,
                   "must_change_password": False}
        found = SimpleNamespace(id="existing-auth-7")
        with mocked_supabase_auth_module(), self.admin(), \
                patch.object(user_routes.usuario_service, "get_by_id_including_inactive", return_value=current), \
                patch.object(user_routes.usuario_service, "email_belongs_uniquely_to", return_value=True), \
                patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE), \
                patch.object(supabase_auth, "find_user_by_email", return_value=found), \
                patch.object(supabase_auth, "update_user", return_value=found) as update_auth, \
                patch.object(supabase_auth, "authenticate", return_value={"id": "existing-auth-7"}), \
                patch.object(supabase_auth, "delete_user") as delete_auth, \
                patch.object(user_routes.usuario_service, "update", side_effect=RuntimeError("local write failed")):
            response = self.client.post("/api/v2/usuarios-setores/usuario/7/access", json={"senha_inicial": "temporary-123"})
        self.assertEqual(response.status_code, 400)
        update_auth.assert_called_once()
        delete_auth.assert_not_called()

    def test_access_status_respects_auth_mode(self):
        user = {"auth_user_id": None, "must_change_password": False}
        with patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.SUPABASE):
            self.assertEqual(user_routes._with_access_status(user)["access_status"], "pending")
        with patch.object(user_routes, "get_current_database_mode", return_value=DatabaseMode.MYSQL):
            self.assertEqual(user_routes._with_access_status(user)["access_status"], "ready")
            self.assertEqual(user_routes._with_access_status({**user, "must_change_password": True})["access_status"], "password_change_required")


if __name__ == "__main__":
    unittest.main()
