"""Prevent outbound commercial mutations in collection adapters."""
import ast
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[2]/'nistiprint_shared'/'services'/'platform_drivers'


class ReadOnlyReplicationTests(unittest.TestCase):
    def test_collection_http_calls_use_get_only(self):
        cases={
            'mercadolivre_catalog.py':None,'shopee_catalog.py':None,
            'mercadolivre_insights.py':{'get'},'shopee_insights.py':{'get'},
            'mercadolivre.py':{'get_orders_list'},'shopee.py':{'get_orders_list_page'},
        }
        for filename,functions in cases.items():
            tree=ast.parse((ROOT/filename).read_text(encoding='utf-8'))
            scopes=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and (functions is None or node.name in functions)]
            with self.subTest(filename=filename):
                self.assertTrue(scopes)
                for scope in scopes:
                    for node in ast.walk(scope):
                        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='requests':
                            self.assertEqual(node.func.attr,'get',f'{filename}:{node.lineno}')
                        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='request_json' and node.args:
                            call=node.args[0]
                            self.assertTrue(isinstance(call,ast.Attribute) and isinstance(call.value,ast.Name) and call.value.id=='requests' and call.attr=='get',f'{filename}:{node.lineno}')
