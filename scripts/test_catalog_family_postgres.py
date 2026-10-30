"""Validate adoption concurrently in an explicitly disposable database."""
import concurrent.futures
import os
from pathlib import Path
import threading
import unittest


@unittest.skipUnless(os.getenv('CATALOG_FAMILY_TEST_DSN'), 'Requires disposable CATALOG_FAMILY_TEST_DSN')
class FamilyConcurrencyTests(unittest.TestCase):
    def test_concurrent_adoption_creates_only_one_parent(self):
        import psycopg2
        dsn = os.environ['CATALOG_FAMILY_TEST_DSN']
        with psycopg2.connect(dsn) as db:
            with db.cursor() as cursor:
                cursor.execute('select current_database()')
                if not cursor.fetchone()[0].startswith('nistiprint_family_test_'):
                    raise RuntimeError('Refusing non-test database')
                seed = (Path(__file__).resolve().parents[1] / 'supabase/tests/catalogo_organizacao.sql').read_text()
                cursor.execute(seed.split('DO $$')[0].replace('BEGIN;', ''))
        barrier = threading.Barrier(2)
        def adopt():
            with psycopg2.connect(dsn) as db:
                with db.cursor() as cursor:
                    barrier.wait(timeout=10)
                    cursor.execute('select catalogo_organizar_anuncio(101)')
                    return cursor.fetchone()[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: adopt(), range(2)))
        self.assertEqual(sorted(r['status'] for r in results), ['created','unchanged'])
        self.assertEqual(len({r['produto_pai_id'] for r in results}), 1)
        with psycopg2.connect(dsn) as db:
            with db.cursor() as cursor:
                cursor.execute('select count(*) from produtos where parent_id=%s',(results[0]['produto_pai_id'],))
                self.assertEqual(cursor.fetchone()[0],2)


if __name__ == '__main__': unittest.main()
