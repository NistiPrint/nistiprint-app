"""Real PostgreSQL acceptance tests for the stock command migration.

Set NISTIPRINT_TEST_DATABASE_URL to a disposable loopback database named
``nistiprint_test`` to opt into this standalone PostgreSQL acceptance suite.
CI supplies an ephemeral PostgreSQL service. The suite refuses to run against
any other database name or a non-loopback host.
"""

from __future__ import annotations

import json
import hashlib
import os
import threading
import unittest
import uuid
from contextlib import closing, contextmanager
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

import psycopg2


DATABASE_URL = os.getenv("NISTIPRINT_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[4]


@unittest.skipUnless(DATABASE_URL, "requires isolated NISTIPRINT_TEST_DATABASE_URL")
class StockCommandPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parsed = urlparse(DATABASE_URL)
        database_name = parsed.path.lstrip("/")
        if database_name != "nistiprint_test" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError("PostgreSQL acceptance tests only allow loopback database nistiprint_test")

        # A plain function assigned here becomes a descriptor and receives
        # the test instance as an unexpected positional argument.
        cls.connection_factory = partial(psycopg2.connect, DATABASE_URL)
        schema_fixture = ROOT / "supabase/tests/fixtures/estoque_command_schema.sql"
        migration = ROOT / "supabase/migrations/20261009175729_estoque_comando_idempotente.sql"
        allocation_migration = ROOT / "supabase/migrations/20261009181200_alocacoes_transacionais.sql"
        consumption_migration = ROOT / "supabase/migrations/20261009191857_consumo_diario_agregado.sql"
        report_migration = ROOT / "supabase/migrations/20261010153814_relatorio_consumo_mensal_ledger.sql"
        reconciliation_permissions_migration = ROOT / "supabase/migrations/20261012160000_revoke_direct_production_reconciliation.sql"
        with closing(cls.connection_factory()) as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(schema_fixture.read_text(encoding="utf-8"))
                    cursor.execute(migration.read_text(encoding="utf-8"))
                    cursor.execute(allocation_migration.read_text(encoding="utf-8"))
                    cursor.execute(consumption_migration.read_text(encoding="utf-8"))
                    cursor.execute(report_migration.read_text(encoding="utf-8"))
                    cursor.execute(reconciliation_permissions_migration.read_text(encoding="utf-8"))

    @contextmanager
    def _connection(self):
        with closing(self.connection_factory()) as connection:
            with connection:
                yield connection

    def setUp(self):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("TRUNCATE public.estoque_operacoes, public.movimentacoes_estoque, "
                           "public.demanda_alocacoes_estoque, public.estoque_atual, "
                           "public.produtos, public.depositos "
                           "RESTART IDENTITY CASCADE")
            cursor.execute("INSERT INTO public.produtos(id, nome) VALUES (1, 'Papel'), (2, 'Insumo 2')")
            cursor.execute("INSERT INTO public.depositos(id) VALUES (1), (2)")

    @staticmethod
    def _movement(product_id=1, deposit_id=1, quantity="1", movement_type="ENTRADA"):
        return {
            "produto_id": product_id,
            "deposito_id": deposit_id,
            "tipo_movimentacao": movement_type,
            "quantidade": quantity,
            "motivo": "isolated PostgreSQL acceptance test",
        }

    def _execute_command(self, connection, operation_id, content_hash, movements):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT public.executar_comando_estoque(%s, %s, %s, %s::jsonb, %s, %s::jsonb)",
                (
                    operation_id,
                    "ENTRADA",
                    content_hash,
                    json.dumps({"source_id": operation_id}),
                    None,
                    json.dumps(movements),
                ),
            )
            return cursor.fetchone()[0]

    def _reserve_allocations(self, connection, operation_id, allocations, *, content_hash=None):
        if content_hash is None:
            canonical = json.dumps(allocations, sort_keys=True, separators=(",", ":"))
            content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT public.reservar_alocacoes_estoque(%s, %s, %s::jsonb, %s, %s, %s::jsonb)",
                (operation_id, content_hash, json.dumps({"source_id": operation_id}),
                 None, 1, json.dumps(allocations)),
            )
            return cursor.fetchone()[0]

    @staticmethod
    def _allocation(item_id, demanda_id, correlation_id, quantity="1"):
        return {
            "produto_id": 1,
            "quantidade": quantity,
            "item_id": str(item_id),
            "demanda_id": str(demanda_id),
            "correlation_id": str(correlation_id),
        }

    def test_simultaneous_stock_creation_keeps_one_balance_and_both_movements(self):
        barrier = threading.Barrier(2)

        def write(operation_id):
            with closing(self.connection_factory()) as connection:
                barrier.wait(timeout=10)
                result = self._execute_command(connection, operation_id, "same-payload", [self._movement()])
                connection.commit()
                return result

        operation_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, operation_ids))

        self.assertTrue(all(result["status"] == "CONFIRMADO" for result in results))
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*), sum(saldo_atual) FROM public.estoque_atual WHERE produto_id=1 AND deposito_id=1")
            self.assertEqual(cursor.fetchone(), (1, 2))
            cursor.execute("SELECT count(*) FROM public.movimentacoes_estoque")
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_concurrent_replay_of_same_operation_has_one_effect(self):
        barrier = threading.Barrier(2)
        operation_id = str(uuid.uuid4())

        def write(_):
            with closing(self.connection_factory()) as connection:
                barrier.wait(timeout=10)
                result = self._execute_command(connection, operation_id, "stable-hash", [self._movement()])
                connection.commit()
                return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(write, range(2)))

        self.assertEqual(first, second)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT saldo_atual FROM public.estoque_atual WHERE produto_id=1 AND deposito_id=1")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT count(*) FROM public.movimentacoes_estoque")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_simultaneous_reservations_preserve_backorder_and_both_allocations(self):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO public.estoque_atual(produto_id, deposito_id, saldo_atual) VALUES (1, 1, 1)"
            )

        barrier = threading.Barrier(2)
        allocations = [
            self._allocation(101, "D-101", uuid.uuid4()),
            self._allocation(102, "D-102", uuid.uuid4()),
        ]
        operation_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        def reserve(index):
            with closing(self.connection_factory()) as connection:
                barrier.wait(timeout=10)
                result = self._reserve_allocations(
                    connection, operation_ids[index], [allocations[index]]
                )
                connection.commit()
                return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, range(2)))

        self.assertTrue(all(result["status"] == "CONFIRMADO" for result in results))
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT saldo_atual, reservado, disponivel FROM public.estoque_atual "
                "WHERE produto_id=1 AND deposito_id=1"
            )
            self.assertEqual(cursor.fetchone(), (1, 2, -1))
            cursor.execute("SELECT count(*) FROM public.demanda_alocacoes_estoque")
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_reservation_retry_is_idempotent_and_changed_content_conflicts(self):
        operation_id = str(uuid.uuid4())
        allocation = self._allocation(101, "D-101", uuid.uuid4(), "2")
        with self._connection() as connection:
            original = self._reserve_allocations(connection, operation_id, [allocation])
            connection.commit()
            replay = self._reserve_allocations(connection, operation_id, [allocation])
            connection.commit()
            self.assertEqual(original, replay)

            changed = self._allocation(101, "D-101", uuid.uuid4(), "3")
            with self.assertRaises(psycopg2.Error) as caught:
                self._reserve_allocations(connection, operation_id, [changed])
            self.assertEqual(caught.exception.pgcode, "23505")
            connection.rollback()

        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT reservado FROM public.estoque_atual WHERE produto_id=1 AND deposito_id=1")
            self.assertEqual(cursor.fetchone()[0], 2)
            cursor.execute("SELECT count(*) FROM public.demanda_alocacoes_estoque")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_invalid_later_allocation_rolls_back_reservation_and_first_row(self):
        operation_id = str(uuid.uuid4())
        allocations = [
            self._allocation(101, "D-101", uuid.uuid4(), "2"),
            {"produto_id": 1, "quantidade": "1", "item_id": "102", "demanda_id": "D-102"},
        ]
        with closing(self.connection_factory()) as connection:
            with self.assertRaises(psycopg2.Error):
                self._reserve_allocations(connection, operation_id, allocations)
            connection.rollback()

        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM public.estoque_operacoes WHERE operation_id=%s", (operation_id,))
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT count(*) FROM public.demanda_alocacoes_estoque")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT count(*) FROM public.estoque_atual")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_failure_on_second_movement_rolls_back_first_balance_and_movement(self):
        operation_id = str(uuid.uuid4())
        movements = [
            self._movement(product_id=1, quantity="5"),
            {"produto_id": 2, "deposito_id": 1, "tipo_movimentacao": "ENTRADA"},
        ]
        with closing(self.connection_factory()) as connection:
            with self.assertRaises(psycopg2.Error):
                self._execute_command(connection, operation_id, "partial-failure", movements)
            connection.rollback()

        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM public.estoque_operacoes WHERE operation_id=%s", (operation_id,))
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT count(*) FROM public.movimentacoes_estoque")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT count(*) FROM public.estoque_atual")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_committed_retry_is_a_no_op_and_conflicting_payload_is_rejected(self):
        operation_id = str(uuid.uuid4())
        movement = self._movement()
        with self._connection() as connection:
            original = self._execute_command(connection, operation_id, "stable-hash", [movement])
            connection.commit()
            replay = self._execute_command(connection, operation_id, "stable-hash", [movement])
            connection.commit()
            self.assertEqual(original, replay)

            with self.assertRaises(psycopg2.Error) as caught:
                self._execute_command(connection, operation_id, "different-hash", [movement])
            self.assertEqual(caught.exception.pgcode, "23505")
            connection.rollback()

        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT saldo_atual FROM public.estoque_atual WHERE produto_id=1 AND deposito_id=1")
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT count(*) FROM public.movimentacoes_estoque")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_execute_is_only_granted_to_service_role(self):
        signature = "public.executar_comando_estoque(uuid,text,text,jsonb,integer,jsonb)"
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT has_function_privilege('anon', %s, 'EXECUTE'), "
                           "has_function_privilege('authenticated', %s, 'EXECUTE'), "
                           "has_function_privilege('service_role', %s, 'EXECUTE')",
                           (signature, signature, signature))
            self.assertEqual(cursor.fetchone(), (False, False, True))

    def test_production_reconciliation_helper_is_internal_to_lease_wrapper(self):
        direct_signature = "public.reconciliar_item_estoque(integer,integer,jsonb,jsonb,uuid,character varying)"
        wrapper_signature = (
            "public.confirmar_reconciliacao_producao(uuid,text,integer,integer,jsonb,jsonb,"
            "uuid,text,text,uuid,uuid[])"
        )
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT has_function_privilege('anon', %s, 'EXECUTE'), "
                "has_function_privilege('authenticated', %s, 'EXECUTE'), "
                "has_function_privilege('service_role', %s, 'EXECUTE'), "
                "has_function_privilege('postgres', %s, 'EXECUTE'), "
                "has_function_privilege('service_role', %s, 'EXECUTE')",
                (direct_signature, direct_signature, direct_signature, direct_signature, wrapper_signature),
            )
            self.assertEqual(cursor.fetchone(), (False, False, False, True, True))

    def test_monthly_consumption_matches_confirmed_movements_and_compensations(self):
        operations = [
            ("11111111-1111-4111-8111-111111111111", "consumption-aug"),
            ("22222222-2222-4222-8222-222222222222", "compensation-aug"),
            ("33333333-3333-4333-8333-333333333333", "consumption-sep"),
        ]
        movements = [
            ("CONS_MP", 5, "2026-08-01T10:00:00", operations[0][0]),
            ("COMPENSACAO_CONS_MP", 1, "2026-08-02T10:00:00", operations[1][0]),
            ("CONS_INT", 2, "2026-09-01T10:00:00", operations[2][0]),
            ("BALANCO", 20, "2026-09-02T10:00:00", None),
        ]
        with self._connection() as connection, connection.cursor() as cursor:
            for operation_id, content_hash in operations:
                cursor.execute(
                    "INSERT INTO public.estoque_operacoes "
                    "(operation_id, command_type, content_hash, status, result, confirmed_at) "
                    "VALUES (%s, 'ENTRADA', %s, 'CONFIRMADO', '{}'::jsonb, now())",
                    (operation_id, content_hash),
                )
            for movement_type, quantity, created_at, operation_id in movements:
                cursor.execute(
                    "INSERT INTO public.movimentacoes_estoque "
                    "(produto_id, deposito_id, tipo_movimentacao, quantidade, "
                    "data_movimentacao, operation_id) "
                    "VALUES (1, 1, %s, %s, %s::timestamp, %s)",
                    (movement_type, quantity, created_at, operation_id),
                )
            cursor.execute(
                "SELECT periodo, consumo_liquido, movimentos "
                "FROM public.relatorio_consumo_mensal_produto(1)"
            )
            rows = cursor.fetchall()
            cursor.execute(
                "SELECT produto_id, total_periodo, periodo_dias, nome_insumo "
                "FROM public.consumo_medio_diario(3660)"
            )
            daily_rows = cursor.fetchall()

        self.assertEqual([(row[0], row[1]) for row in rows], [("2026-08", 4), ("2026-09", 2)])
        self.assertEqual(
            [movement["tipo"] for movement in rows[0][2]],
            ["CONS_MP", "COMPENSACAO_CONS_MP"],
        )
        self.assertEqual(
            [movement["operation_id"] for movement in rows[0][2]],
            [operations[0][0], operations[1][0]],
        )
        self.assertEqual([movement["tipo"] for movement in rows[1][2]], ["CONS_INT"])
        self.assertEqual(daily_rows, [(1, 6, 3660, "Papel")])


if __name__ == "__main__":
    unittest.main()
