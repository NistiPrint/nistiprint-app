"""Suite isolada: usa URL local sem banco/projeto Supabase de producao."""
import os
import sys
import unittest
from pathlib import Path
import jwt

ROOT = Path(__file__).resolve().parents[3]
os.environ['SUPABASE_URL'] = 'http://127.0.0.1:9'
os.environ['SUPABASE_SERVICE_KEY'] = jwt.encode({'role': 'service_role', 'iss': 'local-test'}, 'local-test-secret-with-no-server-access', algorithm='HS256')
for path in [ROOT / 'packages/shared', ROOT / 'packages/shared/tests/services', ROOT / 'apps/api', ROOT / 'apps/api/tests', ROOT / 'apps/worker', ROOT / 'apps/worker/tests']:
    sys.path.insert(0, str(path))

modules = sys.argv[1:] or [
    'test_logistics_canonicalization', 'test_marketplace_logistics_facts', 'test_logistica_manutencao_service',
    'test_logistica_sync_service', 'test_logistica_coleta_service', 'test_canonical_order_snapshot_service',
    'test_marketplace_adapters', 'test_marketplace_webhook_ingest_service', 'test_marketplace_http',
    'test_order_status_canonicalization', 'test_canonical_order_status_service', 'test_marketplace_lifecycle_service',
    'test_bling_order_processing_service', 'test_ressincronizacao_pendentes', 'test_reliable_ingest_service',
    'test_logistica_api', 'test_despacho_janela_service', 'test_despacho_esteira', 'test_despacho_publicar', 'test_celery_config',
]
result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
sys.exit(0 if result.wasSuccessful() else 1)
