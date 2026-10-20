import unittest
from datetime import date
from unittest.mock import MagicMock,patch
from nistiprint_shared.services import gestao_report_repository as repository
from nistiprint_shared.services.gestao_service import analyze


class RepositoryTests(unittest.TestCase):
    def setUp(self): repository._cache.clear()

    def test_warm_cache_uses_only_revision_and_never_scans_orders(self):
        db=MagicMock();start,end=date(2026,10,1),date(2026,10,19)
        payload=analyze([],start,end)
        payload['options']={}
        def rpc(name,args):
            result=MagicMock()
            result.execute.return_value.data=1 if name=='gestao_report_revision' else payload
            return result
        db.rpc.side_effect=rpc
        with patch('nistiprint_shared.services.gestao_service.paginate',return_value=[]),patch.object(repository,'add_planning'):
            first=repository.report(db,start,end,{},False)
            calls=db.rpc.call_count
            second=repository.report(db,start,end,{},False)
            self.assertEqual(db.rpc.call_count,calls+1)
            self.assertEqual(db.rpc.call_args.args[0],'gestao_report_revision')
            self.assertEqual(first,second)
            second['summary']['sales']=999
            self.assertEqual(repository.report(db,start,end,{},False)['summary']['sales'],0)
        db.table.assert_not_called()

    def test_financial_and_commercial_cache_keys_are_separate(self):
        db=MagicMock();start,end=date(2026,10,1),date(2026,10,19)
        def rpc(name,args):
            result=MagicMock()
            result.execute.return_value.data=1 if name=='gestao_report_revision' else analyze([],start,end,include_finance=args['p_finance'])
            return result
        db.rpc.side_effect=rpc
        with patch('nistiprint_shared.services.gestao_service.paginate',return_value=[]),patch.object(repository,'add_planning'):
            commercial=repository.report(db,start,end,{},False)
            financial=repository.report(db,start,end,{},True)
            self.assertNotIn('profitability',commercial)
            self.assertIn('profitability',financial)
        reads=[c.args[1]['p_finance'] for c in db.rpc.call_args_list if c.args[0]=='gestao_report_cached']
        self.assertEqual(reads,[False,True])


if __name__=='__main__': unittest.main()
