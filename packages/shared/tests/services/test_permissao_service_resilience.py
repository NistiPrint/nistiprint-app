import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nistiprint_shared.database.supabase_db_service import supabase_db  # noqa: E402
from nistiprint_shared.services import permissao_service as permission_module  # noqa: E402


class TestPermissionServiceResilience(unittest.TestCase):
    def test_none_permission_response_denies_without_raising(self):
        query = MagicMock()
        with patch.object(
            permission_module,
            'get_current_database_mode',
            return_value=SimpleNamespace(name='SUPABASE'),
        ), patch.object(supabase_db, 'table', return_value=query), patch.object(
            supabase_db,
            'execute_with_retry',
            side_effect=[
                SimpleNamespace(data={
                    'id': 12,
                    'ativo': True,
                    'is_admin': False,
                    'setor_id': 3,
                }),
                None,
            ],
        ):
            allowed = permission_module.permissao_service.has_permission(
                12, 'central_operacoes', 'ler'
            )

        self.assertFalse(allowed)

    def test_permission_query_error_denies_without_raising(self):
        query = MagicMock()
        with patch.object(
            permission_module,
            'get_current_database_mode',
            return_value=SimpleNamespace(name='SUPABASE'),
        ), patch.object(supabase_db, 'table', return_value=query), patch.object(
            supabase_db,
            'execute_with_retry',
            side_effect=[
                SimpleNamespace(data={
                    'id': 12,
                    'ativo': True,
                    'is_admin': False,
                    'setor_id': 3,
                }),
                RuntimeError('permission query unavailable'),
            ],
        ):
            allowed = permission_module.permissao_service.has_permission(
                12, 'central_operacoes', 'ler'
            )

        self.assertFalse(allowed)


if __name__ == '__main__':
    unittest.main()
