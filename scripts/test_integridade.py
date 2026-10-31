"""Executa o conjunto de aceite focado em integridade operacional."""

from __future__ import annotations

import os
import logging
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for relative in (
    "packages/shared",
    "apps/worker",
    "apps/api/tests",
    "apps/worker/tests",
    "apps/local_agent",
):
    sys.path.insert(0, str(ROOT / relative))

# This suite uses mocks and isolated PostgreSQL only. Never inherit a real
# project's URL or service key from the caller's shell or CI environment.
os.environ["SUPABASE_URL"] = "http://127.0.0.1:54321"
os.environ["SUPABASE_SERVICE_KEY"] = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdWIiLCJyZWYiOiJ0ZXN0Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSJ9.signature"
)

TEST_MODULES = (
    "tests.services.test_bom_kit_validation",
    "tests.services.test_product_import_metadata",
    "tests.services.test_alocacao_reserva_producao",
    "tests.services.test_integration_secret_service",
    "tests.services.test_installed_integration_service",
    "tests.services.test_token_manager_compat",
    "tests.services.test_demanda_bom_intent",
    "tests.services.test_estoque_outbox_service",
    "tests.services.test_inventory_service",
    "tests.services.test_motor_jit_guards",
    "tests.services.test_production_decrease_guard",
    "tests.services.test_consumption_service",
    "tests.services.test_report_service",
    "tests.services.test_previsao_consumo_auditoria",
    "tests.services.test_previsao_consumo_atomica",
    "tests.services.test_priority_calculation_service",
    "test_bom_effective",
    "test_estoque_service_comandos",
    "test_access_control",
    "tests.services.test_marketplace_webhook_ingest_service",
    "tests.services.test_catalog_item_refresh",
    "tests.services.test_marketplace_order_replication",
    "tests.services.test_mercadolivre_billing_fee",
    "tests.services.test_replication_read_only",
    "tests.services.test_mercadolivre_personalization_service",
    "tests.services.test_mercadolivre_personalization_parallelism",
    "tests.services.test_mercadolivre_ai_batch",
    "tests.services.test_ressincronizacao_pendentes",
    "tests.services.test_marketplace_logistics_facts",
    "tests.services.test_ordem_producao_atomica",
    "tests.services.test_coleta_demanda_atomica",
    "tests.services.test_reliable_ingest_service",
    "tests.services.test_webhook_monitoring_service",
    "test_celery_config",
    "test_mercadolivre_personalization_tasks",
    "test_reliable_ingest_worker",
    "test_n8n_envelope_fixtures",
    "test_token_renewal_tasks",
    "test_agent",
    "test_updater",
)

if os.getenv("NISTIPRINT_TEST_DATABASE_URL"):
    TEST_MODULES = (
        "tests.services.test_estoque_command_postgres",
        "tests.services.test_mercadolivre_ai_batch_postgres",
        *TEST_MODULES,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nistiprint-agent-tests-") as app_data:
        os.environ["LOCALAPPDATA"] = app_data
        try:
            suite = unittest.TestSuite()
            loader = unittest.defaultTestLoader
            for module in TEST_MODULES:
                suite.addTests(loader.loadTestsFromName(module))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1
        finally:
            # The local agent opens a FileHandler inside this temporary folder.
            # Release it before cleanup; Windows cannot unlink an open log.
            logging.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
