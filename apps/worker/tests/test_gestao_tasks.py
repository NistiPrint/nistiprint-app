import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from nistiprint_shared.database.supabase_db_service import supabase_db
with patch.object(supabase_db,'table',return_value=MagicMock()):
    import celery_config
    from tasks import gestao_tasks


class WorkerTests(unittest.TestCase):
    def test_schedule_is_bounded_and_lower_priority(self):
        schedule=celery_config.gestao_schedules()['gestao-refresh']
        self.assertEqual(schedule['kwargs'],{'limit':100})
        self.assertEqual(schedule['options']['queue'],'gestao_projection')
        self.assertEqual(schedule['options']['expires'],4)
        self.assertEqual(schedule['schedule'],5)

    def test_tasks_are_registered(self):
        for name in ('tasks.gestao_tasks.refresh','tasks.gestao_tasks.collect','tasks.gestao_tasks.collect_due'):
            self.assertIn(name,celery_config.celery_app.tasks)

    def test_empty_batch_does_not_load_catalog(self):
        with patch.object(gestao_tasks,'supabase_db') as db,patch.object(gestao_tasks,'paginate') as scan:
            db.rpc.return_value.execute.return_value.data=[]
            self.assertEqual(gestao_tasks.refresh.run(),{'processed':0})
            scan.assert_not_called()

    def test_backfill_continues_only_after_success(self):
        with patch('nistiprint_shared.services.gestao_collection_service.collect_batch',return_value={'status':'available','has_more':True}), \
             patch.object(gestao_tasks.collect,'apply_async') as dispatch:
            gestao_tasks.collect.run(6,'shopee_escrow')
            self.assertEqual(dispatch.call_args.kwargs['countdown'],15)
        with patch('nistiprint_shared.services.gestao_collection_service.collect_batch',return_value={'status':'forbidden','has_more':False}), \
             patch.object(gestao_tasks.collect,'apply_async') as dispatch:
            gestao_tasks.collect.run(6,'shopee_escrow')
            dispatch.assert_not_called()

    def test_enrichment_rollout_flag_prevents_external_collection(self):
        with patch.dict('os.environ',{'MARKETPLACE_INSIGHTS_ENABLED':'0'}),patch('nistiprint_shared.services.gestao_collection_service.collect_batch') as collect:
            self.assertEqual(gestao_tasks.collect.run(6,'shopee_escrow'),{'status':'disabled'})
            collect.assert_not_called()

    def test_invalid_projection_does_not_discard_valid_orders_in_batch(self):
        sources=[{'order':{'id':1}},{'order':{'id':2}}]
        with patch.object(gestao_tasks,'supabase_db') as db,patch.object(gestao_tasks,'paginate',return_value=[]),patch.object(gestao_tasks,'project',side_effect=[AttributeError('bad source'),{'id':2}]):
            def rpc(name,args):
                result=MagicMock()
                result.execute.return_value.data=sources if name=='gestao_claim' else 1
                return result
            db.rpc.side_effect=rpc
            self.assertEqual(gestao_tasks.refresh.run(),{'processed':1,'claimed':2})
            self.assertEqual(db.rpc.call_args.args,('gestao_finish',{'p_rows':[{'id':2}]}))


if __name__=='__main__':
    unittest.main()
