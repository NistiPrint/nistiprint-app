import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[4]
APP_API_PATH = REPO_ROOT / 'apps' / 'api'
SHARED_PATH = REPO_ROOT / 'packages' / 'shared'

for path in (str(APP_API_PATH), str(SHARED_PATH)):
    if path not in sys.path:
        sys.path.insert(0, path)

import routes.demanda_producao_api as demanda_producao_api  # noqa: E402


class FakeLogsQuery:
    def __init__(self, data):
        self._data = data
        self.eq_calls = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.eq_calls.append((field, value))
        return self

    def neq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return type('Result', (), {'data': self._data})()


class TestDemandaProducaoApiResilience(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_api_list_demandas_ignores_invalid_entries(self):
        mocked_demandas = [
            None,
            {'id': 1, 'manual_priority_score': 5, 'modalidade_logistica': 'STANDARD', 'data_entrega': '2026-05-14'},
            'invalid',
        ]

        with self.app.app_context():
            with patch.object(demanda_producao_api.demanda_producao_service, 'get_all_demandas', return_value=mocked_demandas):
                response = demanda_producao_api.api_list_demandas()

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(len(payload['demandas']), 1)
        self.assertEqual(payload['demandas'][0]['id'], 1)

    def test_dashboard_totals_ignores_invalid_demandas_and_bad_dates(self):
        logs_query = FakeLogsQuery([
            {'quantidade_produzida': 2, 'detalhes_producao': {'campo': 'capas_impressas_qtd'}},
            'invalid-log',
        ])
        demandas = [
            None,
            {'id': 1, 'data_entrega': '2026-05-14'},
            {'id': 2, 'data_entrega': '2026-05-20'},
            {'id': 3, 'data_entrega': 'invalid-date'},
        ]

        with self.app.app_context():
            with patch('nistiprint_shared.database.supabase_db_service.supabase_db.table', return_value=logs_query), \
                 patch.object(demanda_producao_api.demanda_producao_service, 'get_all_demandas', return_value=demandas), \
                 patch.object(demanda_producao_api, 'get_today', return_value=date(2026, 5, 14)):
                response = demanda_producao_api.get_dashboard_totals()

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(payload['sector_totals']['CPD'], 2.0)
        self.assertEqual(payload['demand_totals']['today'], 1)
        self.assertEqual(payload['demand_totals']['future'], 1)

    def test_dashboard_totals_uses_app_timezone_today_source(self):
        logs_query = FakeLogsQuery([])

        with self.app.app_context():
            with patch('nistiprint_shared.database.supabase_db_service.supabase_db.table', return_value=logs_query), \
                 patch.object(demanda_producao_api.demanda_producao_service, 'get_all_demandas', return_value=[]), \
                 patch.object(demanda_producao_api, 'get_today', return_value=date(2030, 1, 2)):
                response = demanda_producao_api.get_dashboard_totals()

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertIn(('data', '2030-01-02'), logs_query.eq_calls)


if __name__ == '__main__':
    unittest.main()
