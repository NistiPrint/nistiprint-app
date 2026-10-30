import unittest

from nistiprint_shared.services.bom_lote_planejamento import planejar_composicao, validar_grafo


class TestBomLotePlanejamento(unittest.TestCase):
    def test_alteracoes_preservam_componentes_ocultos_e_origem(self):
        original = [
            {'componente_id': 1, 'quantidade_necessaria': '2', 'is_inherited': True, 'grupo': 'A'},
            {'componente_id': 2, 'quantidade_necessaria': '3', 'unidade_medida': 'kg'},
        ]
        result = planejar_composicao(original, [
            {'acao': 'definir', 'componente_id': 1, 'quantidade': '0.125'},
            {'acao': 'definir', 'componente_id': 3, 'quantidade': '1'},
        ])
        self.assertEqual(result[0]['quantidade_necessaria'], '0.125')
        self.assertTrue(result[0]['is_inherited'])
        self.assertEqual(result[1], original[1])
        self.assertEqual(original[0]['quantidade_necessaria'], '2')

    def test_exclusao_e_validacao(self):
        self.assertEqual(planejar_composicao([{'componente_id': 1}], [{'acao': 'remover', 'componente_id': 1}]), [])
        for valor in ('0', '-1', 'NaN', '1.0000001', '1000000000'):
            with self.assertRaises(ValueError):
                planejar_composicao([], [{'acao': 'definir', 'componente_id': 1, 'quantidade': valor}])

    def test_rejeita_duplicatas(self):
        with self.assertRaisesRegex(ValueError, 'BOM_DUPLICATE_COMPONENT'):
            planejar_composicao([{'componente_id': 1}, {'componente_id': 1}], [])
        with self.assertRaisesRegex(ValueError, 'BOM_DUPLICATE_OPERATION'):
            planejar_composicao([], [{'acao': 'remover', 'componente_id': 1}] * 2)

    def test_detecta_ciclo_formado_por_multiplas_alteracoes(self):
        grafo = {1: [{'componente_id': 2}], 2: [{'componente_id': 3}], 3: [{'componente_id': 1}]}
        with self.assertRaisesRegex(ValueError, 'BOM_CYCLE: 1 -> 2 -> 3 -> 1'):
            validar_grafo(grafo)

    def test_aceita_componentes_compartilhados(self):
        validar_grafo({1: [{'componente_id': 3}], 2: [{'componente_id': 3}], 3: []})


if __name__ == '__main__':
    unittest.main()
