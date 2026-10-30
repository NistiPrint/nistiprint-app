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
        cls.db.autocommit=False
        root=Path(__file__).resolve().parents[4]
        with cls.db.cursor() as cursor:
            # Refuse to touch any existing application database.
            cursor.execute("select to_regclass('public.pedidos')")
            if cursor.fetchone()[0]:
                raise RuntimeError('Fixture requires an empty disposable database')
            cursor.execute((root/'supabase/tests/fixtures/gestao_schema.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261020160000_gestao_business_intelligence.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261020200000_marketplace_insights.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261023120000_catalogo_anuncios_gestao_items.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261023130000_marketplace_catalog_variation_attributes.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261029180000_catalogo_completion.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261029190000_gestao_historical_review.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261029200000_catalogo_clone_compat.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261029210000_catalogo_reconciliation_pending.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261029220000_gestao_traffic_calendar.sql').read_text(encoding='utf-8'))
            cursor.execute((root/'supabase/migrations/20261029230000_gestao_preserve_attribution.sql').read_text(encoding='utf-8'))
            legacy=(root/'supabase/migrations/20260926130000_clonar_produto_interno.sql').read_text(encoding='utf-8')
            cursor.execute(legacy[legacy.index('CREATE OR REPLACE FUNCTION public.validar_ativacao_variacao_clonada()'):])
            cursor.execute((root/'supabase/migrations/20261029235900_catalogo_canonical_activation.sql').read_text(encoding='utf-8'))
        cls.db.commit()
        cls.db.autocommit=True

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
        import psycopg2
        self.c.execute("INSERT INTO produtos(id,sku,nome,status,formato,atributos) VALUES(10,'MODEL','Modelo','ativo','com_variacao','{}')")
        axes=[{'name':'Cor','options':['Azul'],'posicao':1}]
        variants=[{'sku':'MODEL-A','status':'ativo','variation_values':{'Cor':'Azul'}},
                  {'sku':'MODEL-B','status':'ativo','variation_values':{'Cor':'Azul'}}]
        self.c.execute('SAVEPOINT atomic_family_test')
        with self.assertRaises(psycopg2.errors.UniqueViolation):
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

    def test_catalog_page_releases_lease_for_immediate_continuation(self):
        self.c.execute('SELECT marketplace_catalog_sync_claim(6)')
        first = self.c.fetchone()[0]
        self.c.execute("SELECT marketplace_catalog_sync_store_page(6,%s,'[]','{\"offset\":5}',false)", (first['owner_token'],))
        self.assertTrue(self.c.fetchone()[0])
        self.c.execute('SELECT marketplace_catalog_sync_claim(6)')
        second = self.c.fetchone()[0]
        self.assertNotEqual(second['status'], 'busy')
        self.assertNotEqual(second['owner_token'], first['owner_token'])
        self.assertEqual(second['checkpoint'], {'offset': 5})
        self.c.execute("SELECT marketplace_catalog_sync_store_page(6,%s,'[]','{}',true)", (first['owner_token'],))
        self.assertFalse(self.c.fetchone()[0])

    def test_statistics_rejects_expired_owner_and_keeps_metric_tables_atomic(self):
        self.c.execute("INSERT INTO gestao_coletas(account_id,capability,enabled,status) VALUES(6,'shopee_product',true,'pending')")
        self.c.execute("SELECT gestao_statistics_claim(6,'shopee_product')")
        owner = self.c.fetchone()[0]['owner_token']
        row = {'resource_id':'100','day':'2026-10-01','kind':'counter','metrics':{'views':0},
               'source':'shopee_product','resource_type':'listing','timezone':'America/Sao_Paulo','semantic':'contador_acumulado'}
        self.c.execute("SELECT gestao_statistics_metric(6,'shopee_product',%s,%s)", (owner,json.dumps(row)))
        self.assertTrue(self.c.fetchone()[0])
        self.c.execute('SELECT count(*) FROM gestao_metricas_anuncio_periodo')
        self.assertEqual(self.c.fetchone()[0], 1)
        self.c.execute("UPDATE gestao_coletas SET lease_until=now()-interval '1 second'")
        row['metrics']['views'] = 999
        self.c.execute("SELECT gestao_statistics_metric(6,'shopee_product',%s,%s)", (owner,json.dumps(row)))
        self.assertFalse(self.c.fetchone()[0])
        self.c.execute("SELECT metrics->>'views' FROM gestao_metricas_anuncio_periodo")
        self.assertEqual(self.c.fetchone()[0], '0')

    def test_family_two_real_transactions_reject_stale_writer(self):
        import psycopg2
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(2)
        with psycopg2.connect(os.environ['GESTAO_TEST_DSN']) as setup:
            with setup.cursor() as c:
                c.execute("INSERT INTO produtos(id,sku,nome,papel_catalogo) VALUES(18000,'CONCURRENT','Concorrência','modelo')")
        def writer():
            connection = psycopg2.connect(os.environ['GESTAO_TEST_DSN'])
            try:
                barrier.wait(timeout=10)
                with connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout='10s'")
                        cursor.execute("SELECT catalogo_salvar_familia(18000,1,'[]','[]')")
                return 'ok'
            except psycopg2.Error as exc:
                return exc.pgcode
            finally:
                connection.close()
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(lambda _: writer(), range(2)))
            self.assertCountEqual(outcomes, ['ok','40001'])
        finally:
            with psycopg2.connect(os.environ['GESTAO_TEST_DSN']) as cleanup:
                with cleanup.cursor() as c:
                    c.execute('DELETE FROM produtos WHERE id=18000')

    def test_historical_preview_is_actor_bound_and_single_use(self):
        self.finish([project(self.claim()[0],Catalog([{'id':2,'sku':'ABC'}],[],[]))])
        scope = {'account_id':6,'date_from':'2026-10-01','date_to':'2026-10-01'}
        self.c.execute("SELECT gestao_item_reprocessamento_previa(1,%s,'Revisão explícita')", (json.dumps(scope),))
        preview = self.c.fetchone()[0]
        self.assertEqual(preview['orders'],1)
        self.c.execute('SAVEPOINT other_actor')
        with self.assertRaises(Exception):
            self.c.execute('SELECT gestao_item_reprocessamento_confirmar(%s,2)', (preview['token'],))
        self.c.execute('ROLLBACK TO SAVEPOINT other_actor')
        self.c.execute('SELECT gestao_item_reprocessamento_confirmar(%s,1)', (preview['token'],))
        self.assertEqual(self.c.fetchone()[0]['status'],'queued')
        self.c.execute('SELECT gestao_item_reprocessamento_batch(%s,25)', (preview['token'],))
        self.assertEqual(self.c.fetchone()[0]['status'],'complete')
        self.c.execute('SELECT count(*) FROM gestao_item_reprocessamento_itens WHERE processed_at IS NOT NULL')
        self.assertEqual(self.c.fetchone()[0],1)

    def test_performance_pagination_unknown_subtotal_and_currencies(self):
        self.finish([project(self.claim()[0],Catalog([{'id':2,'sku':'ABC'}],[],[]))])
        self.c.execute("SELECT gestao_desempenho('2026-10-01','2026-10-01','{}','produto',1,0,'orders','asc')")
        report = self.c.fetchone()[0]
        self.assertEqual(report['total_rows'],1)
        self.assertEqual(report['totals']['orders'],1)
        self.assertEqual(report['coverage']['orders_materialized'],1)
        self.assertFalse(report['coverage']['traffic_available'])

    def test_cloning_family_copies_canonical_values_in_same_transaction(self):
        self.c.execute("INSERT INTO produtos(id,sku,nome,papel_catalogo) VALUES(17000,'CLONE-MODEL','Modelo','modelo')")
        axes = [{'name':'Cor','options':['Azul'],'posicao':1}]
        variants = [{'sku':'CLONE-AZ','nome':'Azul','variation_values':{'Cor':'Azul'}}]
        self.c.execute('SELECT catalogo_salvar_familia(17000,1,%s,%s)',(json.dumps(axes),json.dumps(variants)))
        self.c.execute("SELECT id FROM produtos WHERE parent_id=17000")
        child = self.c.fetchone()[0]
        self.c.execute('SELECT clonar_produto_interno(17000,%s,NULL,%s)',('CLONED',json.dumps({str(child):'CLONED-AZ'})))
        cloned = self.c.fetchone()[0]
        self.assertEqual(cloned['papel_catalogo'],'modelo')
        self.c.execute('SELECT count(*) FROM produto_variacao_combinacoes WHERE produto_pai_id=%s',(cloned['id'],))
        self.assertEqual(self.c.fetchone()[0],1)

    def test_models_reject_new_stock_and_sellable_links(self):
        self.c.execute("INSERT INTO produtos(id,sku,nome,papel_catalogo) VALUES(16000,'MODEL-GUARD','Modelo','modelo')")
        for statement in ("INSERT INTO movimentacoes_estoque(produto_id) VALUES(16000)",
                          "INSERT INTO produto_anuncios(produto_id,integration_id,item_externo_id) VALUES(16000,6,'100')"):
            self.c.execute('SAVEPOINT model_guard')
            with self.assertRaises(Exception):
                self.c.execute(statement)
            self.c.execute('ROLLBACK TO SAVEPOINT model_guard')

    def test_cloned_draft_can_activate_after_assigning_canonical_combination(self):
        self.c.execute("INSERT INTO produtos(id,sku,nome,papel_catalogo) VALUES(15000,'ACTIVATE','Modelo','modelo')")
        axes=[{'name':'Cor','options':['Azul','Vermelho'],'posicao':1}]
        self.c.execute('SELECT catalogo_salvar_familia(15000,1,%s,%s)',(json.dumps(axes),json.dumps([
            {'sku':'ACTIVATE-AZ','variation_values':{'Cor':'Azul'}}])))
        self.c.execute("SELECT id FROM produtos WHERE sku='ACTIVATE-AZ'")
        origin=self.c.fetchone()[0]
        self.c.execute("SELECT clonar_produto_interno(%s,'ACTIVATE-RED')",(origin,))
        clone=self.c.fetchone()[0]
        self.c.execute('SELECT catalogo_versao FROM produtos WHERE id=15000')
        version=self.c.fetchone()[0]
        self.c.execute('SELECT catalogo_salvar_familia(15000,%s,%s,%s)',(version,json.dumps(axes),json.dumps([
            {'produto_id':clone['id'],'status':'ativo','variation_values':{'Cor':'Vermelho'}}])))
        self.c.execute('SET CONSTRAINTS catalog_validate_active_variation IMMEDIATE')
        self.c.execute('SELECT status FROM produtos WHERE id=%s',(clone['id'],))
        self.assertEqual(self.c.fetchone()[0],'ativo')

    def test_variation_requires_existing_model_parent(self):
        self.c.execute('SAVEPOINT invalid_parent')
        with self.assertRaises(Exception):
            self.c.execute("INSERT INTO produtos(sku,nome,parent_id,papel_catalogo) VALUES('INVALID','Inválida',2,'variacao')")
        self.c.execute('ROLLBACK TO SAVEPOINT invalid_parent')

    def test_two_variations_share_visits_without_duplicating_order_total(self):
        self.finish([project(self.claim()[0],Catalog([{'id':2,'sku':'ABC'}],[],[]))])
        self.c.execute("INSERT INTO produtos(id,sku,nome) VALUES(3,'DEF','Produto B')")
        self.c.execute("INSERT INTO marketplace_anuncios(integration_id,item_externo_id) VALUES(6,'100') RETURNING id")
        announcement = self.c.fetchone()[0]
        items = [
            {'id':11,'product_id':2,'mapping':'matched','sku':'ABC','listing':'100','variation':'1',
             'announcement_id':announcement,'quantity':1,'subtotal':10},
            {'id':12,'product_id':3,'mapping':'matched','sku':'DEF','listing':'100','variation':'2',
             'announcement_id':announcement,'quantity':2,'subtotal':None},
        ]
        self.c.execute('UPDATE gestao_fatos_pedido SET payload=payload||%s WHERE pedido_id=1',
                       (json.dumps({'currency':'BRL','items':items}),))
        self.c.execute("INSERT INTO gestao_metricas_anuncio_periodo(account_id,recurso_tipo,resource_id,periodo_inicio,periodo_fim,source,kind,fuso_origem,semantica,metrics) VALUES(6,'listing','100','2026-10-01','2026-10-01','fixture','visits','America/Sao_Paulo','diaria','{\"visits\":100}')")
        self.c.execute("SELECT gestao_desempenho('2026-10-01','2026-10-01','{}','produto',100,0,'sales','desc')")
        report = self.c.fetchone()[0]
        self.assertEqual(report['totals']['orders'],1)
        self.assertEqual(report['totals']['units'],3)
        self.assertEqual(report['totals']['sales'],10)
        self.assertEqual(report['totals']['known_subtotals'],1)
        self.assertEqual(len(report['traffic']),1)
        self.assertEqual(report['traffic'][0]['order_visit_rate'],1)
        self.c.execute("UPDATE gestao_metricas_anuncio_periodo SET fuso_origem='UTC'")
        self.c.execute("SELECT gestao_desempenho('2026-10-01','2026-10-01','{}','produto',100,0,'sales','desc')")
        utc_report = self.c.fetchone()[0]
        self.assertIsNone(utc_report['traffic'][0]['order_visit_rate'])
        self.assertEqual(utc_report['traffic'][0]['fuso_origem'],'UTC')

    def test_performance_never_sums_different_currencies(self):
        catalog=Catalog([{'id':2,'sku':'ABC'}],[],[])
        self.finish([project(self.claim()[0],catalog)])
        self.c.execute("UPDATE gestao_fatos_pedido SET payload=payload||'{\"currency\":\"BRL\"}' WHERE pedido_id=1")
        self.c.execute("INSERT INTO pedidos VALUES(2,6,null,null,null,'shopee','2026-10-01T10:00:00-03:00','delivered',20)")
        self.c.execute("INSERT INTO itens_pedido VALUES(12,2,2,'ABC',1,20,20)")
        self.finish([project(row,catalog) for row in self.claim()])
        self.c.execute("UPDATE gestao_fatos_pedido SET payload=payload||'{\"currency\":\"USD\"}' WHERE pedido_id=2")
        self.c.execute("SELECT gestao_desempenho('2026-10-01','2026-10-01','{}','produto',100,0,'sales','desc')")
        report=self.c.fetchone()[0]
        self.assertEqual(report['totals']['currency_count'],2)
        self.assertIsNone(report['totals']['sales'])
        self.assertEqual({row['currency'] for row in report['rows']},{'BRL','USD'})


if __name__=='__main__':
    unittest.main()
