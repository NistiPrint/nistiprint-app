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
            cursor.execute((root/'supabase/migrations/20261023120000_catalogo_anuncios_gestao_items.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261023130000_marketplace_catalog_variation_attributes.sql').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.db.autocommit=False
        self.c=self.db.cursor()
        self.c.execute("INSERT INTO installed_integrations(id,instance_name,platform_slug,module_id) VALUES(6,'Loja A','shopee','shopee'); INSERT INTO produtos(id,preco_custo,sku,nome) VALUES(2,10,'ABC','Produto A');")
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

    def test_family_rpc_creates_canonical_values_and_rejects_stale_versions(self):
        self.c.execute("INSERT INTO produtos(id,sku,nome,status,formato,atributos) VALUES(10,'MODEL','Modelo','ativo','com_variacao','{\"variations_config\":[]}')")
        axes=[{'name':'Cor','options':['Azul','Vermelho'],'posicao':1}]
        variants=[{'sku':'MODEL-AZ','nome':'Modelo Azul','status':'ativo','variation_values':{'Cor':'Azul'}}]
        self.c.execute('SELECT catalogo_salvar_familia(10,1,%s::jsonb,%s::jsonb)',(json.dumps(axes),json.dumps(variants)))
        self.assertEqual(self.c.fetchone()[0]['catalogo_versao'],2)
        self.c.execute("SELECT papel_catalogo FROM produtos WHERE sku='MODEL-AZ'")
        self.assertEqual(self.c.fetchone()[0],'variacao')
        self.c.execute('SELECT count(*) FROM produto_variacao_combinacoes WHERE produto_pai_id=10')
        self.assertEqual(self.c.fetchone()[0],1)
        self.c.execute('SAVEPOINT stale_version_test')
        with self.assertRaises(Exception):
            self.c.execute('SELECT catalogo_salvar_familia(10,1,%s::jsonb,%s::jsonb)',(json.dumps(axes),json.dumps(variants)))
        self.c.execute('ROLLBACK TO SAVEPOINT stale_version_test')

    def test_legacy_catalog_backfill_supplies_required_axis_codes(self):
        self.c.execute("SELECT codigo FROM produto_eixos WHERE nome='Cor'")
        self.assertTrue(self.c.fetchone()[0])
        self.c.execute("SELECT codigo FROM produto_eixo_opcoes WHERE nome='Azul'")
        self.assertTrue(self.c.fetchone()[0])
        self.c.execute('SELECT count(*) FROM produto_variacao_valores WHERE produto_id=9001')
        self.assertEqual(self.c.fetchone()[0],1)

    def test_family_save_is_atomic_when_two_variants_claim_same_combination(self):
        self.c.execute("INSERT INTO produtos(id,sku,nome,status,formato,atributos) VALUES(10,'MODEL','Modelo','ativo','com_variacao','{}')")
        axes=[{'name':'Cor','options':['Azul'],'posicao':1}]
        variants=[{'sku':'MODEL-A','status':'ativo','variation_values':{'Cor':'Azul'}},
                  {'sku':'MODEL-B','status':'ativo','variation_values':{'Cor':'Azul'}}]
        self.c.execute('SAVEPOINT atomic_family_test')
        with self.assertRaises(Exception):
            self.c.execute('SELECT catalogo_salvar_familia(10,1,%s::jsonb,%s::jsonb)',(json.dumps(axes),json.dumps(variants)))
        self.c.execute('ROLLBACK TO SAVEPOINT atomic_family_test')
        self.c.execute('SELECT count(*) FROM produto_pai_eixos WHERE produto_pai_id=10')
        self.assertEqual(self.c.fetchone()[0],0)
        self.c.execute('SELECT catalogo_versao FROM produtos WHERE id=10')
        self.assertEqual(self.c.fetchone()[0],1)

    def test_order_refresh_preserves_audited_item_attribution_until_explicit_rebuild(self):
        self.c.execute("INSERT INTO produtos(id,preco_custo,sku,nome) VALUES(99,5,'OTHER','Produto B')")
        self.finish([project(self.claim()[0],Catalog([{'id':2,'sku':'ABC'}],[],[]))])
        changed={'items':[{'id':11,'product_id':99,'mapping':'matched','sku':'ABC','quantity':2,'subtotal':100}]}
        self.c.execute('UPDATE gestao_fatos_pedido SET payload=payload||%s::jsonb WHERE pedido_id=1',(json.dumps(changed),))
        self.c.execute('SELECT produto_id FROM gestao_fatos_item WHERE pedido_id=1')
        self.assertEqual(self.c.fetchone()[0],2)
        self.c.execute("SELECT gestao_replace_item_facts(1,%s::jsonb)",(json.dumps([{'chave_grupo':'sku:abc','produto_id':99,'origem_atribuicao':'matched','quantidade':2,'subtotal':100,'sold_on':'2026-10-01'}]),))
        self.c.execute('SELECT produto_id FROM gestao_fatos_item WHERE pedido_id=1')
        self.assertEqual(self.c.fetchone()[0],99)

    def test_item_fact_backfill_is_paged_and_rebuilds_missing_rows(self):
        self.finish([project(self.claim()[0],Catalog([{'id':2,'sku':'ABC'}],[],[]))])
        self.c.execute('DELETE FROM gestao_fatos_item WHERE pedido_id=1')
        self.c.execute('SELECT gestao_backfill_order_item_facts(0,1)')
        result=self.c.fetchone()[0]
        self.assertEqual(result['processed'],1)
        self.assertFalse(result['has_more'])
        self.c.execute('SELECT count(*),max(produto_id) FROM gestao_fatos_item WHERE pedido_id=1')
        self.assertEqual(self.c.fetchone(),(1,2))


if __name__=='__main__':
    unittest.main()
