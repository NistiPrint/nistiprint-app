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

from routes.impressao import (  # noqa: E402
    _nome_destinatario_mercadolivre,
    _print_sort_key,
)


def pedido(numero_loja, tags, total_items=None, hascustom=None, plataforma_slug=None):
    itens = [{'custom_tag': t} for t in tags]
    return {
        'numeroLoja': numero_loja,
        'itens': itens,
        'total_items': total_items if total_items is not None else len(itens),
        'hasCustomItem': hascustom
        if hascustom is not None
        else int(any((t or '').strip() for t in tags)),
        'plataforma_slug': plataforma_slug,
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

    def test_mercadolivre_ordena_numero_externo_crescente(self):
        pedidos = [
            pedido('100', [], plataforma_slug='mercadolivre'),
            pedido('99', [], plataforma_slug='mercadolivre'),
            pedido('1000', [], plataforma_slug='mercadolivre'),
        ]
        self.assertEqual(self.ordenar(pedidos), ['99', '100', '1000'])

    def test_mercadolivre_desempata_por_texto(self):
        pedidos = [
            pedido('MELI-B', [], plataforma_slug='mercadolivre'),
            pedido('MELI-A', [], plataforma_slug='mercadolivre'),
            pedido('10', [], plataforma_slug='mercadolivre'),
        ]
        self.assertEqual(self.ordenar(pedidos), ['10', 'MELI-A', 'MELI-B'])

    def test_mercadolivre_desempata_textualmente_ids_numericos_equivalentes(self):
        pedidos = [
            pedido('1', [], plataforma_slug='mercadolivre'),
            pedido('001', [], plataforma_slug='mercadolivre'),
        ]
        self.assertEqual(self.ordenar(pedidos), ['001', '1'])

    def test_mercadolivre_prioriza_nome_do_comprador(self):
        nome = _nome_destinatario_mercadolivre(
            logistics={'address': {'receiver_name': 'Maria da Silva'}},
            customer={
                'name': 'apelido-do-usuario',
                'nickname': 'apelido-do-usuario',
                'raw': {'first_name': 'Joao', 'last_name': 'Santos'},
            },
            platform_fields={},
            fallback='apelido-do-usuario',
        )
        self.assertEqual(nome, 'Joao Santos')

    def test_mercadolivre_faz_fallback_para_nome_e_sobrenome(self):
        nome = _nome_destinatario_mercadolivre(
            logistics={'address': {}},
            customer={
                'name': 'apelido-do-usuario',
                'raw': {'first_name': 'Joao', 'last_name': 'Santos'},
            },
            platform_fields={},
            fallback='apelido-do-usuario',
        )
        self.assertEqual(nome, 'Joao Santos')

    def test_mercadolivre_sem_endereco_nao_quebra(self):
        nome = _nome_destinatario_mercadolivre(
            logistics={}, customer={}, platform_fields={}, fallback='Nome legado'
        )
        self.assertEqual(nome, 'Nome legado')

    def test_mercadolivre_procura_endereco_no_payload_bruto(self):
        nome = _nome_destinatario_mercadolivre(
            logistics={'address': {'city': 'Sao Paulo'}},
            customer={'name': 'apelido-do-usuario'},
            platform_fields={
                'mercadolivre': {
                    'shipment': {
                        'receiver_address': {'receiver_name': 'Ana Souza'},
                    },
                },
            },
            fallback='apelido-do-usuario',
        )
        self.assertEqual(nome, 'Ana Souza')


if __name__ == '__main__':
    unittest.main()
