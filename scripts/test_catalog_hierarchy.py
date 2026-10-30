import copy
import unittest
from prepare_catalog_hierarchy import prepare


class HierarchyTests(unittest.TestCase):
    def example(self,title='Caderno capa dura',description='Caderno A5 com capa dura e 100 páginas.',item='1'):
        source={'account_id':6,'provider':'shopee','item_id':item,'status':'NORMAL','title':title,'description':description,'images':[],
                'unit':{'id':'','sku':'PA-1','attributes':{},'images':[]}}
        record={'key':'6:1:','sku':'PA-1','name':title,'existing_id':None,'category_id':11,'structure':'manufaturado','sources':[source],'bom':[],'pending':[]}
        manifest={'version':1,'run_id':'run','products':[record],'items':[source],'families':[],'coverage':{},'assumptions':[]}
        baseline={'produtos':[],'ficha_tecnica':[]}
        snapshot={'produtos':[{'id':1,'sku':'PA-1','nome':title,'tipo_produto':'PRODUTO_ACABADO','categoria_id':11,
                               'atributos':{'importacao_catalogo':{'key':record['key'],'run_id':'run'}}}], 'ficha_tecnica':[]}
        return manifest,baseline,snapshot

    def test_book_has_core_and_two_intermediate_covers_without_guessed_materials(self):
        manifest,delta,_=prepare(*self.example())
        intermediates=[p for p in delta['products'] if p.get('pi_intermediate')]
        self.assertEqual(len(intermediates),3)
        self.assertTrue(all(p['material_type']=='intermediario' and not p['bom'] for p in intermediates))
        self.assertEqual(len(manifest['products'][0]['bom']),3)
        self.assertTrue(all(line['quantity']==1 for line in manifest['products'][0]['bom']))

    def test_desk_pad_does_not_gain_invented_covers(self):
        _,delta,_=prepare(*self.example('Planner de mesa A4','Bloco com folhas destacáveis para planejamento.'))
        self.assertEqual([p['pi_role'] for p in delta['products'] if p.get('pi_intermediate')],['miolo'])

    def test_pack_of_twenty_cores_keeps_twenty_physical_units(self):
        manifest,_,_=prepare(*self.example('Miolo de agenda — 20 unidades','20 miolos de agenda 2022.',item='MLB2013183410'))
        self.assertEqual(manifest['products'][0]['bom'][0]['quantity'],20)

    def test_original_manufacturing_recipes_are_not_restructured(self):
        manifest,baseline,snapshot=self.example()
        manifest['products'][0]['existing_id']=1
        baseline['produtos']=copy.deepcopy(snapshot['produtos'])
        _,delta,_=prepare(manifest,baseline,snapshot)
        self.assertEqual(delta['products'],[])

    def test_printing_material_moves_to_pi_without_changing_its_quantity(self):
        manifest,baseline,snapshot=self.example('Kit adesivos','Quatro folhas A5 de vinil adesivo.')
        manifest['products'][0]['bom']=[{'key':'material:vinil-adesivo-a5','quantity':4,'unit':'un'}]
        snapshot['produtos'].append({'id':2,'atributos':{'importacao_catalogo':{'key':'material:vinil-adesivo-a5'}}})
        snapshot['ficha_tecnica']=[{'id':50,'produto_pai_id':1,'componente_id':2,'quantidade_necessaria':4,'unidade_medida':'un'}]
        updated,delta,_=prepare(manifest,baseline,snapshot)
        pi=next(p for p in delta['products'] if p.get('pi_intermediate'))
        self.assertEqual(pi['bom'][0]['quantity'],4)
        self.assertEqual(updated['products'][0]['bom'],[{'key':pi['key'],'quantity':1,'unit':'un','evidence':'Um conjunto de impressos/recortes por unidade do produto anunciado.'}])
        root=next(p for p in delta['products'] if not p.get('pi_intermediate'))
        self.assertEqual(root['move_bom'][0]['line_id'],50)
        self.assertEqual(root['move_bom'][0]['target_key'],pi['key'])


if __name__=='__main__':unittest.main()
