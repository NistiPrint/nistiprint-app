"""Run only against an explicitly supplied disposable loopback nistiprint_test."""
import json
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

URL = os.getenv('NISTIPRINT_TEST_DATABASE_URL')
ROOT = Path(__file__).resolve().parents[4]


@unittest.skipUnless(URL,'requires isolated NISTIPRINT_TEST_DATABASE_URL')
class MercadoLivreBatchPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parsed=urlparse(URL)
        if parsed.hostname not in {'localhost','127.0.0.1','::1'} or parsed.path.lstrip('/') != 'nistiprint_test':
            raise RuntimeError('Only isolated loopback nistiprint_test is allowed')
        with closing(psycopg2.connect(URL)) as connection, connection, connection.cursor() as cursor:
            for name in ['supabase/tests/fixtures/mercadolivre_ai_batch_schema.sql',
                         'supabase/migrations/20261009100000_preserve_ml_personalization_during_reprocessing.sql',
                         'supabase/migrations/20261013150000_mercadolivre_deferred_ai_retry.sql',
                         'supabase/migrations/20261013200000_ai_execution_source_and_item_force.sql']:
                cursor.execute((ROOT/name).read_text(encoding='utf-8'))

    def sql(self,text,params=()):
        with closing(psycopg2.connect(URL)) as connection, connection, connection.cursor() as cursor:
            cursor.execute(text,params)
            return cursor.fetchall() if cursor.description else []

    def setUp(self):
        self.sql('TRUNCATE public.mercadolivre_personalization_batches,public.mercadolivre_personalization_logs, '
                 'public.mercadolivre_personalizations,public.installed_integrations,public.pedidos, '
                 'public.itens_pedido,public.mercadolivre_chat_conversations RESTART IDENTITY CASCADE')
        self.sql("INSERT INTO public.installed_integrations VALUES (7,'mercadolivre'),(8,'mercadolivre');"
                 "INSERT INTO public.pedidos VALUES (101,7,'mercadolivre'),(102,7,'mercadolivre');"
                 "INSERT INTO public.itens_pedido VALUES (101,101),(102,102)")

    def batch(self,account=7,packs=('p','q')):
        batch_id=str(uuid.uuid4())
        self.sql('INSERT INTO public.mercadolivre_personalization_batches(id,marketplace_integration_id,total,pack_ids) '
                 'VALUES(%s,%s,%s,%s)',(batch_id,account,len(packs),json.dumps(list(packs))))
        for pack in packs:
            self.sql('INSERT INTO public.mercadolivre_personalization_batch_items(batch_id,marketplace_integration_id,pack_id) '
                     'VALUES(%s,%s,%s)',(batch_id,account,pack))
        return batch_id

    def claim(self,batch_id,token=None,account=7):
        token=token or str(uuid.uuid4())
        rows=self.sql('SELECT * FROM public.ml_ai_claim_batch(%s,%s,%s)',(account,batch_id,token))
        return token,rows

    def item(self,batch_id,token,pack='p'):
        return self.sql('SELECT attempts,persistence_attempts FROM public.ml_ai_claim_item(%s,%s,%s)',(batch_id,pack,token))

    def finish(self,batch_id,token,status,pack='p'):
        return self.sql("SELECT public.ml_ai_finish_item(%s,%s,%s,%s,'test','2000-01-01','{}',NULL,'MODEL')",
                        (batch_id,pack,token,status))[0][0]

    def release(self,batch_id,token):
        return self.sql('SELECT status,phase,processed,success_count,failed_count,retry_total,retry_processed '
                        'FROM public.ml_ai_release_batch(%s,%s)',(batch_id,token))[0]

    def payload(self,batch_id,records=None):
        records=records or [{'pedido_id':101,'item_pedido_id':101,'provider_order_id':'order-101',
                             'provider_item_id':'local-item-101','quantity_to_personalize':1,
                             'customization_name':'Ana','details':{}}]
        return dict(p_integration_id=7,p_pack_id='p',p_batch_id=batch_id,p_context_hash='hash',
                    p_status='SUCCESS',p_needs_review=False,p_records=records,
                    p_log={'pedido_ids':[101],'input_data':'prompt','model_result':{},'metadata':{}})

    def test_first_pass_barrier_retry_budget_and_idempotent_progress(self):
        b=self.batch()
        token,_=self.claim(b)
        self.assertEqual(self.item(b,token),[(1,0)])
        self.assertTrue(self.finish(b,token,'RETRY_PENDING'))
        self.assertEqual(self.item(b,token),[])
        self.assertFalse(self.finish(b,token,'FAILED'))
        self.assertEqual(self.item(b,token,'q'),[(1,0)])
        self.finish(b,token,'COMPLETED','q')
        self.assertEqual(self.release(b,token)[:5],('PENDING','RETRY',2,1,0))
        retry_token,_=self.claim(b)
        self.assertEqual(self.item(b,retry_token),[(2,0)])
        self.finish(b,retry_token,'FAILED')
        self.assertEqual(self.release(b,retry_token),('COMPLETED','DONE',2,1,1,1,1))
        self.assertEqual(self.claim(b)[1],[])

    def test_concurrent_batches_share_one_account_slot_and_accounts_are_independent(self):
        first,second=self.batch(),self.batch()
        ready=threading.Barrier(2)
        def acquire(batch):
            ready.wait(timeout=3)
            return self.claim(batch)[1]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(acquire,first),pool.submit(acquire,second)]
            claims=[future.result(timeout=5) for future in futures]
        self.assertEqual(sum(bool(rows) for rows in claims),1)
        independent=self.batch(account=8,packs=('other',))
        self.assertTrue(self.claim(independent,account=8)[1])

    def test_manual_batch_merges_under_the_account_lease_and_tracks_the_subscriber(self):
        active=self.batch(packs=('p',))
        token,_=self.claim(active)
        requested=self.batch(packs=('q',))
        merged=self.sql('SELECT public.ml_ai_merge_manual_packs(7,%s,%s)',(active,requested))[0][0]
        self.assertTrue(merged['merged'])
        self.assertEqual(merged['added'],1)
        self.assertEqual(self.sql('SELECT total,pack_ids FROM public.mercadolivre_personalization_batches WHERE id=%s',(active,)),
                         [(2,['p','q'])])
        self.assertEqual(self.sql('SELECT pack_id,status FROM public.mercadolivre_personalization_batch_items '
                                  'WHERE batch_id=%s ORDER BY pack_id',(active,)),
                         [('p','RUNNING'),('q','PENDING')])
        self.assertEqual(self.sql('SELECT count(*) FROM public.mercadolivre_personalization_batches WHERE id=%s',(requested,)),
                         [(0,)])
        self.sql('INSERT INTO public.usuarios(id) VALUES(1)')
        self.sql('INSERT INTO public.mercadolivre_personalization_batch_subscribers(batch_id,user_id) VALUES(%s,1)',
                 (active,))
        self.assertEqual(self.sql('SELECT user_id FROM public.mercadolivre_personalization_batch_subscribers '
                                  'WHERE batch_id=%s',(active,)),[(1,)])
        self.assertTrue(token)

    def test_saved_result_survives_restart_and_stale_token_cannot_write(self):
        b=self.batch(packs=('p',))
        token,_=self.claim(b)
        self.item(b,token)
        payload=self.payload(b)
        self.sql("SELECT public.ml_ai_checkpoint_result(%s,'p',%s,%s,'{}')",(b,token,json.dumps(payload)))
        self.sql("UPDATE public.mercadolivre_personalization_batches SET lease_until=now()-interval '1 second' WHERE id=%s",(b,))
        current,_=self.claim(b)
        self.assertEqual(self.item(b,current),[(1,2)])
        with self.assertRaises(psycopg2.Error):
            self.sql("SELECT public.ml_ai_persist_result(%s,'p',%s,'{}')",(b,token))
        result=self.sql("SELECT public.ml_ai_persist_result(%s,'p',%s,'{}')",(b,current))[0][0]
        self.assertEqual(result['saved'],1)
        self.assertEqual(self.release(b,current)[:5],('COMPLETED','DONE',1,1,0))
        self.assertEqual(self.sql('SELECT count(*) FROM public.mercadolivre_personalization_logs')[0][0],1)

    def test_invalid_persistence_rolls_back_results_logs_and_counters_together(self):
        b=self.batch(packs=('p',))
        token,_=self.claim(b)
        self.item(b,token)
        payload=self.payload(b)
        payload['p_records'].append({**payload['p_records'][0],'item_pedido_id':999,'provider_item_id':'bad'})
        self.sql("SELECT public.ml_ai_checkpoint_result(%s,'p',%s,%s,'{}')",(b,token,json.dumps(payload)))
        with self.assertRaises(psycopg2.Error):
            self.sql("SELECT public.ml_ai_persist_result(%s,'p',%s,'{}')",(b,token))
        self.assertEqual(self.sql('SELECT count(*) FROM public.mercadolivre_personalizations')[0][0],0)
        self.assertEqual(self.sql('SELECT count(*) FROM public.mercadolivre_personalization_logs')[0][0],0)
        self.assertEqual(self.sql('SELECT processed,success_count FROM public.mercadolivre_personalization_batches WHERE id=%s',(b,)),[(0,0)])

    def test_worker_loss_never_allows_a_third_model_attempt(self):
        b=self.batch(packs=('p',))
        token,_=self.claim(b)
        self.item(b,token)
        self.sql("UPDATE public.mercadolivre_personalization_batches SET lease_until=now()-interval '1 second' WHERE id=%s",(b,))
        recovered,_=self.claim(b)
        self.release(b,recovered)
        retry,_=self.claim(b)
        self.assertEqual(self.item(b,retry),[(2,0)])
        self.sql("UPDATE public.mercadolivre_personalization_batches SET lease_until=now()-interval '1 second' WHERE id=%s",(b,))
        last,_=self.claim(b)
        self.assertEqual(self.item(b,last),[])
        self.assertEqual(self.release(b,last)[:5],('COMPLETED','DONE',1,0,1))
