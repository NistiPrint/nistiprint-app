import unittest
from nistiprint_shared.services.platform_drivers.mercadolivre_insights import observed_sale_fee


class BillingFeeTests(unittest.TestCase):
    def test_net_sale_fee_is_preserved_as_its_own_component(self):
        data={'total':1,'errors':[],'results':[{'order_id':123,'sale_fee':{'net':4.01}}]}
        self.assertEqual(observed_sale_fee(data,'123'),{'sale_fee':4.01})

    def test_zero_is_known_but_partial_or_ambiguous_is_unknown(self):
        row={'order_id':123,'sale_fee':{'net':0}}
        self.assertEqual(observed_sale_fee({'total':1,'errors':[],'results':[row]},'123'),{'sale_fee':0})
        for data in ({'total':2,'errors':[],'results':[row]}, {'total':1,'errors':['bad'],'results':[row]},
                     {'total':2,'errors':[],'results':[row,row]}):
            self.assertEqual(observed_sale_fee(data,'123'),{})
        self.assertEqual(observed_sale_fee({'total':1,'errors':[],'results':[row]},'999'),{})

    def test_pack_can_include_other_orders_if_one_match_is_unique(self):
        rows=[{'order_id':123,'sale_fee':{'net':4.01}},{'order_id':456,'sale_fee':{'net':7}}]
        self.assertEqual(observed_sale_fee({'total':2,'errors':[],'results':rows},'123'),{'sale_fee':4.01})
