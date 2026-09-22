"""Prioridade e associacao das personalizacoes nos papeis de pedido."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.impressao import (  # noqa: E402
    _deve_usar_mensagem_comprador,
    _indexar_personalizacoes,
    _personalizacoes_do_item,
)


class TestPersonalizacoesImpressao(unittest.TestCase):
    def selecionar(self, item, personalizacoes):
        por_item_id, por_descricao = _indexar_personalizacoes(personalizacoes)
        item_ids_validos = {10, 20}
        return _personalizacoes_do_item(
            item,
            por_item_id,
            por_descricao,
            item_ids_validos,
        )

    def test_vinculo_direto_tem_prioridade_sobre_fallback(self):
        direta = {
            'id': 1,
            'item_pedido_id': 10,
            'item_description': 'Capa personalizada',
            'customization_name': 'Maria',
        }
        antiga = {
            'id': 2,
            'item_pedido_id': 999,
            'item_description': 'Capa personalizada',
            'customization_name': 'Nome antigo',
        }

        selecionadas = self.selecionar(
            {'id': 10, 'descricao': 'Capa personalizada'},
            [antiga, direta],
        )

        self.assertEqual(selecionadas, [direta])

    def test_item_pedido_id_obsoleto_faz_fallback_por_descricao(self):
        personalizacao = {
            'id': 3,
            'item_pedido_id': 999,
            'item_description': '  Capa personalizada  ',
            'customization_name': 'Ana',
        }

        selecionadas = self.selecionar(
            {'id': 10, 'descricao': 'Capa personalizada'},
            [personalizacao],
        )

        self.assertEqual(selecionadas, [personalizacao])

    def test_fallback_nao_reaproveita_vinculo_valido_de_outro_item(self):
        personalizacao = {
            'id': 4,
            'item_pedido_id': 20,
            'item_description': 'Capa personalizada',
            'customization_name': 'Beatriz',
        }

        selecionadas = self.selecionar(
            {'id': 10, 'descricao': 'Capa personalizada'},
            [personalizacao],
        )

        self.assertEqual(selecionadas, [])

    def test_nome_textual_preenchido_bloqueia_mensagem(self):
        itens = [{
            'personalizado': True,
            'personalizations': [{'customization_name': '  Joao  '}],
        }]

        self.assertFalse(_deve_usar_mensagem_comprador(itens))

    def test_nome_vazio_nao_bloqueia_mensagem(self):
        itens = [{
            'personalizado': True,
            'personalizations': [
                {'customization_name': '   '},
                {'customization_name': None},
            ],
        }]

        self.assertTrue(_deve_usar_mensagem_comprador(itens))


if __name__ == '__main__':
    unittest.main()
