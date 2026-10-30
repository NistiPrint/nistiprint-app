import unittest
from nistiprint_shared.services.catalogo_lista_service import CatalogoListaService, image_url


class Query:
    def __init__(self, rows): self.rows = rows
    def __getattr__(self, name): return lambda *args, **kwargs: self
    def execute(self): return type('Result', (), {'data': self.rows})()


class Database:
    def __init__(self, products): self.products = products
    def table(self, name): return Query(self.products if name == 'produtos' else [])


class CatalogListTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'id': 1, 'nome': 'Modelo', 'sku': 'M'},
                     {'id': 2, 'nome': 'Azul', 'sku': 'BLUE', 'parent_id': 1},
                     {'id': 3, 'nome': 'Outro', 'sku': 'O'}]

    def test_child_search_includes_parent_and_expands(self):
        rows, pages = CatalogoListaService(Database(self.rows)).list(page=1,per_page=1,q='BLUE')
        self.assertEqual(pages,1)
        self.assertEqual(rows[0]['id'],1)
        self.assertTrue(rows[0]['expand_variants'])
        self.assertEqual([p['id'] for p in rows[0]['variants']],[2])

    def test_family_pagination_does_not_duplicate_children(self):
        service = CatalogoListaService(Database(self.rows))
        rows, pages = service.list(page=2,per_page=1)
        self.assertEqual(pages,2)
        self.assertEqual(rows[0]['id'],1)
        self.assertEqual(len(rows[0]['variants']),1)

    def test_root_sku_search_keeps_children(self):
        rows, _ = CatalogoListaService(Database(self.rows)).list(page=1,per_page=20,q='M')
        self.assertEqual(len(rows[0]['variants']),1)

    def test_image_rejects_credentials_and_non_http_schemes(self):
        self.assertIsNone(image_url({'atributos':{'images':['javascript:alert(1)','https://a:b@example.com/x']}}))
        self.assertEqual(image_url({'atributos':{'images':[{'url':'https://example.com/x'}]}}),'https://example.com/x')
