"""Concurrency test for targeted catalog reads on a disposable database."""
import concurrent.futures
import json
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone


@unittest.skipUnless(os.getenv('CATALOG_FAMILY_TEST_DSN'), 'Requires disposable CATALOG_FAMILY_TEST_DSN')
class CatalogWebhookConcurrency(unittest.TestCase):
    def test_newer_observation_wins_in_either_commit_order(self):
        import psycopg2
        dsn = os.environ['CATALOG_FAMILY_TEST_DSN']
        with psycopg2.connect(dsn) as db, db.cursor() as cursor:
            cursor.execute('select current_database()')
            if not cursor.fetchone()[0].startswith('nistiprint_family_test_'):
                raise RuntimeError('Refusing non-test database')
        barrier = threading.Barrier(2)
        now = datetime.now(timezone.utc)
        def store(n):
            row={'item_externo_id':'MLB999111','titulo':str(n),'unidades':[]}
            with psycopg2.connect(dsn) as db, db.cursor() as cursor:
                barrier.wait(timeout=10)
                cursor.execute('select marketplace_catalog_store_item(%s,%s::jsonb,%s)',
                    (6,json.dumps(row),now + timedelta(seconds=n)))
                return cursor.fetchone()[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(store,[0,1]))
        self.assertIn('updated',results)
        with psycopg2.connect(dsn) as db, db.cursor() as cursor:
            cursor.execute("select titulo from marketplace_anuncios where integration_id=6 and item_externo_id='MLB999111'")
            self.assertEqual(cursor.fetchone()[0],'1')


if __name__ == '__main__': unittest.main()
