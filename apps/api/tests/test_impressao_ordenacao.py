"""Ordem de impressao — contrato herdado do legado.

A chave esta especificada em `kb/legado/services/bling/bling.py`:

    1. itens personalizados: nao depois sim
    2. quais itens personalizados: ordem alfabetica (agrupa por modelo)
    3. quantidade total de itens: ordem crescente
    4. quantos itens diferentes: ordem crescente

A versao anterior mantinha so o criterio 1 e desempatava por `numeroLoja`, que
nao tem relacao com o produto — o agrupamento por modelo se perdia, que e
exatamente o que a pessoa na impressora usa.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.impressao import _print_sort_key  # noqa: E402


def pedido(numero_loja, tags, total_items=None, hascustom=None):
    itens = [{'custom_tag': t} for t in tags]
    return {
        'numeroLoja': numero_loja,
        'itens': itens,
        'total_items': total_items if total_items is not None else len(itens),
        'hasCustomItem': hascustom
        if hascustom is not None
        else int(any((t or '').strip() for t in tags)),
    }


class TestOrdemImpressao(unittest.TestCase):
    def ordenar(self, pedidos):
        return [p['numeroLoja'] for p in sorted(pedidos, key=_print_sort_key)]

    def test_nao_personalizados_vem_antes(self):
        ordem = self.ordenar([
            pedido('COM', ['CAPA-A']),
            pedido('SEM', ['']),
        ])
        self.assertEqual(ordem, ['SEM', 'COM'])

    def test_personalizados_agrupam_por_modelo(self):
        """O criterio que a ordenacao anterior destruia.

        Mesmo tamanho de pedido, tags diferentes: a ordem tem de sair
        alfabetica por tag, nao por numero de loja.
        """
        ordem = self.ordenar([
            pedido('Z9', ['CAPA-C']),
            pedido('A1', ['CAPA-A']),
            pedido('M5', ['CAPA-B']),
        ])
        self.assertEqual(ordem, ['A1', 'M5', 'Z9'])

    def test_pedidos_menores_primeiro(self):
        ordem = self.ordenar([
            pedido('GRANDE', ['CAPA-A'], total_items=10),
            pedido('PEQUENO', ['CAPA-A'], total_items=1),
        ])
        self.assertEqual(ordem, ['PEQUENO', 'GRANDE'])

    def test_desempate_por_itens_distintos(self):
        ordem = self.ordenar([
            pedido('DOIS_ITENS', ['CAPA-A', 'CAPA-A'], total_items=4),
            pedido('UM_ITEM', ['CAPA-A'], total_items=4),
        ])
        self.assertEqual(ordem, ['UM_ITEM', 'DOIS_ITENS'])

    def test_precedencia_completa(self):
        """Personalizado domina tamanho; tamanho domina tag."""
        ordem = self.ordenar([
            pedido('P_GRANDE_A', ['CAPA-A'], total_items=9),
            pedido('P_PEQUENO_Z', ['CAPA-Z'], total_items=1),
            pedido('SIMPLES', [''], total_items=50),
        ])
        self.assertEqual(ordem, ['SIMPLES', 'P_PEQUENO_Z', 'P_GRANDE_A'])

    def test_pedido_sem_itens_nao_quebra(self):
        ordem = self.ordenar([
            pedido('VAZIO', [], total_items=0),
            pedido('COM_TAG', ['CAPA-A']),
        ])
        self.assertEqual(ordem, ['VAZIO', 'COM_TAG'])

    def test_ordenacao_e_estavel_e_deterministica(self):
        pedidos = [
            pedido('B', ['CAPA-A']),
            pedido('A', ['CAPA-A']),
        ]
        self.assertEqual(self.ordenar(pedidos), self.ordenar(pedidos))


if __name__ == '__main__':
    unittest.main()
