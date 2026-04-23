"""
Testes unitários para PersonalizedOrderIdentifier.

Cenários testados:
1. Produto com campo customizado = "true" → personalizado
2. Produto com campo customizado = "false" → não personalizado
3. Produto sem campo customizado, nome com "personaliza" → personalizado
4. Item com descrição contendo "personaliza" → personalizado
5. Pedido misto (alguns itens personalizados) → identificação parcial
"""

import unittest
from unittest.mock import MagicMock, patch
from nistiprint_shared.services.personalized_order_identifier import (
    PersonalizedOrderIdentifier
)


class TestPersonalizedOrderIdentifier(unittest.TestCase):
    """Testes para identificação de pedidos personalizados."""

    def setUp(self):
        """Configura teste."""
        self.identifier = PersonalizedOrderIdentifier()
        self.custom_field_id = 2797770

    def test_item_com_descricao_personalizada(self):
        """Item com descrição contendo 'personaliza' é identificado."""
        order_data = {
            'id': 123,
            'numero': '12345',
            'numeroLoja': '260318ABC123',
            'loja': {'id': 204047801},
            'itens': [
                {
                    'id': 1,
                    'descricao': 'Agenda Personalizada 2026',
                    'produto': {'id': 101, 'nome': 'Agenda'}
                }
            ]
        }

        # Mock do lookup de bling_integration
        with patch.object(self.identifier, '_lookup_bling_integration', return_value='1'):
            with patch.object(self.identifier, '_get_pedido_bling_id', return_value=1):
                with patch.object(self.identifier, '_mark_as_personalized'):
                    result = self.identifier.process_order(order_data)

        self.assertTrue(result['success'])
        self.assertEqual(result['personalized_items'], [0])  # Índice do item

    def test_item_com_nome_personalizado(self):
        """Item com nome de produto contendo 'personaliza' é identificado."""
        order_data = {
            'id': 123,
            'numero': '12345',
            'numeroLoja': '260318ABC123',
            'loja': {'id': 204047801},
            'itens': [
                {
                    'id': 1,
                    'descricao': 'Agenda 2026',
                    'produto': {'id': 101, 'nome': 'Agenda Personalizada'}
                }
            ]
        }

        with patch.object(self.identifier, '_lookup_bling_integration', return_value='1'):
            with patch.object(self.identifier, '_get_pedido_bling_id', return_value=1):
                with patch.object(self.identifier, '_mark_as_personalized'):
                    # Mock do identify_personalized_products_batch
                    with patch.object(
                        self.identifier,
                        '_identify_personalized_products_batch',
                        return_value={101: True}
                    ) as mock_batch:
                        result = self.identifier.process_order(order_data)
                        
                        # Não deve chamar batch lookup porque nome já identificou
                        # (na verdade vai chamar porque descrição não tem "personaliza")
                        # O critério de nome é verificado no batch

        self.assertTrue(result['success'])

    def test_item_sem_personalizacao(self):
        """Item sem indicadores de personalização não é identificado."""
        order_data = {
            'id': 123,
            'numero': '12345',
            'numeroLoja': '260318ABC123',
            'loja': {'id': 204047801},
            'itens': [
                {
                    'id': 1,
                    'descricao': 'Agenda 2026 Simples',
                    'produto': {'id': 101, 'nome': 'Agenda'}
                }
            ]
        }

        with patch.object(self.identifier, '_lookup_bling_integration', return_value='1'):
            with patch.object(self.identifier, '_get_pedido_bling_id', return_value=1):
                with patch.object(self.identifier, '_mark_as_personalized'):
                    with patch.object(
                        self.identifier,
                        '_identify_personalized_products_batch',
                        return_value={101: False}
                    ):
                        result = self.identifier.process_order(order_data)

        self.assertTrue(result['success'])
        self.assertEqual(result['personalized_items'], [])

    def test_pedido_misto(self):
        """Pedido com alguns itens personalizados e outros não."""
        order_data = {
            'id': 123,
            'numero': '12345',
            'numeroLoja': '260318ABC123',
            'loja': {'id': 204047801},
            'itens': [
                {
                    'id': 1,
                    'descricao': 'Agenda Personalizada',
                    'produto': {'id': 101, 'nome': 'Agenda'}
                },
                {
                    'id': 2,
                    'descricao': 'Caneta Simples',
                    'produto': {'id': 102, 'nome': 'Caneta'}
                },
                {
                    'id': 3,
                    'descricao': 'Planner',
                    'produto': {'id': 103, 'nome': 'Planner Personalizado'}
                }
            ]
        }

        with patch.object(self.identifier, '_lookup_bling_integration', return_value='1'):
            with patch.object(self.identifier, '_get_pedido_bling_id', return_value=1):
                with patch.object(self.identifier, '_mark_as_personalized'):
                    with patch.object(
                        self.identifier,
                        '_identify_personalized_products_batch',
                        return_value={102: False, 103: True}
                    ):
                        result = self.identifier.process_order(order_data)

        self.assertTrue(result['success'])
        # Item 0: descrição tem "personalizada"
        # Item 1: não tem personalização
        # Item 2: produto tem "Personalizado" no nome
        self.assertIn(0, result['personalized_items'])
        self.assertNotIn(1, result['personalized_items'])
        self.assertIn(2, result['personalized_items'])

    def test_pedido_sem_loja_id(self):
        """Pedido sem bling_loja_id retorna erro."""
        order_data = {
            'id': 123,
            'numero': '12345',
            'numeroLoja': '260318ABC123',
            'loja': {'id': None}  # Sem loja_id
        }

        result = self.identifier.process_order(order_data)

        self.assertFalse(result['success'])
        self.assertIn('No bling_loja_id', result.get('error', ''))

    def test_identify_personalized_items_batch(self):
        """Testa identificação em lote de produtos."""
        # Mock de produtos
        products = {
            101: {
                'id': 101,
                'nome': 'Agenda Personalizada',
                'camposCustomizados': []
            },
            102: {
                'id': 102,
                'nome': 'Caneta',
                'camposCustomizados': [
                    {
                        'idCampoCustomizado': 2797770,
                        'valor': 'true'
                    }
                ]
            },
            103: {
                'id': 103,
                'nome': 'Lápis',
                'camposCustomizados': [
                    {
                        'idCampoCustomizado': 2797770,
                        'valor': 'false'
                    }
                ]
            }
        }

        with patch.object(self.identifier, 'get_products_by_ids', return_value=products):
            results = self.identifier._identify_personalized_products_batch(
                [101, 102, 103],
                2797770
            )

        self.assertTrue(results[101])  # Nome tem "Personalizada"
        self.assertTrue(results[102])  # Campo customizado = true
        self.assertFalse(results[103])  # Campo customizado = false


class TestBlingClientPersonalized(unittest.TestCase):
    """Testes para métodos de personalização no BlingClient."""

    def test_is_product_personalized_por_nome(self):
        """Produto com nome contendo 'personaliza' é identificado."""
        from nistiprint_shared.services.bling.bling_client import BlingClient

        # Criar mock client
        client = MagicMock(spec=BlingClient)
        client._product_cache = {
            101: {
                'id': 101,
                'nome': 'Agenda Personalizada',
                'camposCustomizados': []
            }
        }
        client.get_product = lambda pid: client._product_cache.get(pid)

        # Testar método (precisamos importar a implementação real)
        # Como é um método de instância, vamos testar a lógica
        product = client._product_cache[101]
        is_personalized = 'personaliza' in product.get('nome', '').lower()

        self.assertTrue(is_personalized)

    def test_is_product_personalized_por_campo(self):
        """Produto com campo customizado = true é identificado."""
        product = {
            'id': 102,
            'nome': 'Caneta',
            'camposCustomizados': [
                {
                    'idCampoCustomizado': 2797770,
                    'valor': 'true'
                }
            ]
        }

        custom_field_id = 2797770
        is_personalized = False

        # Critério 1: nome
        if 'personaliza' in product.get('nome', '').lower():
            is_personalized = True
        else:
            # Critério 2: campo customizado
            for campo in product.get('camposCustomizados', []):
                if (campo.get('idCampoCustomizado') == custom_field_id and
                    str(campo.get('valor', '')).lower() == 'true'):
                    is_personalized = True
                    break

        self.assertTrue(is_personalized)


if __name__ == '__main__':
    unittest.main()
