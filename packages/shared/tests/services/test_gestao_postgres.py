"""Runs only against a deliberately configured disposable database."""
import json
import os
from pathlib import Path
import unittest

from nistiprint_shared.services.gestao_projection import Catalog, project


@unittest.skipUnless(os.getenv('GESTAO_TEST_DSN'),'Requires disposable GESTAO_TEST_DSN')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        cls.db=psycopg2.connect(os.environ['GESTAO_TEST_DSN'])
        cls.db.autocommit=True
        root=Path(__file__).resolve().parents[4]
        with cls.db.cursor() as cursor:
            # Refuse to touch any existing application database.
            cursor.execute("select to_regclass('public.pedidos')")
            if cursor.fetchone()[0]:
                raise RuntimeError('Fixture requires an empty disposable database')
            cursor.execute((root/'supabase/tests/fixtures/gestao_schema.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261020160000_gestao_business_intelligence.sql').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.autocommit=False
        self.c=self.db.cursor()
        self.c.execute("INSERT INTO installed_integrations VALUES(6,'Loja A'); INSERT INTO produtos VALUES(2,10);")
        self.c.execute("INSERT INTO pedidos_shopee VALUES(9,'{\"buyer_user_id\":10,\"create_time\":1790859600}');")
        self.c.execute("INSERT INTO pedidos VALUES(1,6,null,9,null,'shopee','2026-10-01T10:00:00-03:00','delivered',100)")
        self.c.execute("INSERT INTO itens_pedido VALUES(11,1,2,'ABC',2,50,100)")

    def tearDown(self):
        self.db.rollback()
        self.db.autocommit=True
        self.c.close()

    def claim(self):
        self.c.execute('SELECT public.gestao_claim(100)')
        return self.c.fetchone()[0]

    def finish(self,rows):
        self.c.execute('SELECT public.gestao_finish(%s::jsonb)',(json.dumps(rows),))
        return self.c.fetchone()[0]

    def test_projection_and_idempotent_finish(self):
        source=self.claim()[0]
        p=project(source,Catalog([{'id':2,'preco_custo':10}],[],[]))
        self.assertEqual(self.finish([p]),1)
        self.assertEqual(self.finish([p]),0)
        self.c.execute('SELECT count(*) FROM gestao_fatos_pedido')
        self.assertEqual(self.c.fetchone()[0],1)

    def test_update_during_projection_rejects_stale_generation(self):
        source=self.claim()[0]
        self.c.execute('UPDATE itens_pedido SET quantidade=3,subtotal=150 WHERE id=11')
        p=project(source,Catalog([{'id':2,'preco_custo':10}],[],[]))
        self.assertEqual(self.finish([p]),0)
        fresh=self.claim()[0]
        self.assertGreater(fresh['generation'],source['generation'])
        self.assertEqual(fresh['items'][0]['quantidade'],3)

    def test_mirror_update_requeues_only_canonical_order(self):
        first=self.claim()[0]
        self.c.execute("UPDATE pedidos_shopee SET raw_payload=raw_payload||'{\"buyer_user_id\":20}' WHERE id=9")
        p=project(first,Catalog([],[],[]))
        self.finish([p])
        self.assertEqual(self.claim()[0]['shopee']['buyer_user_id'],20)

    def test_catalog_cost_has_actual_effective_time(self):
        self.c.execute('UPDATE produtos SET preco_custo=12 WHERE id=2')
        self.c.execute('SELECT unit_cost,estimated FROM gestao_custos ORDER BY valid_from DESC LIMIT 1')
        self.assertEqual(self.c.fetchone(),(12,True))

    def test_deleting_order_removes_projection(self):
        p=project(self.claim()[0],Catalog([],[],[]))
        self.finish([p])
        self.c.execute('DELETE FROM pedidos WHERE id=1')
        self.c.execute('SELECT count(*) FROM gestao_fatos_pedido')
        self.assertEqual(self.c.fetchone()[0],0)

    def test_collection_lease_is_exclusive(self):
        self.c.execute("SELECT gestao_collection_lease(6,'ml_visits')")
        self.assertTrue(self.c.fetchone()[0])
        self.c.execute("SELECT gestao_collection_lease(6,'ml_visits')")
        self.assertFalse(self.c.fetchone()[0])

    def test_browser_roles_cannot_read_or_write_facts(self):
        import psycopg2
        self.c.execute('SAVEPOINT access_test; SET LOCAL ROLE authenticated')
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            self.c.execute('SELECT * FROM gestao_fatos_pedido')
        self.c.execute('ROLLBACK TO SAVEPOINT access_test')
        self.c.execute('SAVEPOINT rpc_test; SET LOCAL ROLE anon')
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            self.c.execute('SELECT gestao_claim(1)')
        self.c.execute('ROLLBACK TO SAVEPOINT rpc_test')


if __name__=='__main__':
    unittest.main()
