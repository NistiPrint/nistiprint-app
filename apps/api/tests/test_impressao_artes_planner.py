"""The print unit is the PDF, even when it covers two BOM components."""

import unittest
from decimal import Decimal

from nistiprint_shared.services.print_artwork_logic import build_print_groups, legacy_credit


class TestArtworkGroups(unittest.TestCase):
    def setUp(self):
        self.components = {
            10: {"componente_id": 10, "nome": "Capa impressa", "sku": "CAPA", "papel_sugerido": "capa", "quantidade": 1},
            20: {"componente_id": 20, "nome": "Contra capa impressa", "sku": "CONTRA", "papel_sugerido": "contra", "quantidade": 1},
        }

    def groups(self, arts, components=None):
        return build_print_groups(7, arts, components or self.components, [])

    def test_one_pdf_covers_both_components_once(self):
        groups = self.groups([{
            "id": "art-1", "nome": "Par capa e contra", "componentes": [
                {"componente_id": 10, "papel": "capa"},
                {"componente_id": 20, "papel": "contra"},
            ],
        }])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["quantidade_por_unidade"], 1)
        self.assertEqual(groups[0]["componentes_ids"], [10, 20])
        self.assertIsNone(groups[0]["pendencia_arte"])

    def test_separate_pdfs_remain_separate_jobs(self):
        groups = self.groups([
            {"id": "front", "nome": "Capa", "componentes": [{"componente_id": 10, "papel": "capa"}]},
            {"id": "back", "nome": "Contra", "componentes": [{"componente_id": 20, "papel": "contra"}]},
        ])
        self.assertEqual({group["arte_id"] for group in groups}, {"front", "back"})

    def test_unequal_component_quantities_block_print(self):
        components = {**self.components, 20: {**self.components[20], "quantidade": 2}}
        groups = self.groups([{
            "id": "art-1", "nome": "Par", "componentes": [
                {"componente_id": 10, "papel": "capa"}, {"componente_id": 20, "papel": "contra"},
            ],
        }], components)
        self.assertIn("quantidades diferentes", groups[0]["pendencia_arte"])

    def test_uncovered_component_is_pending(self):
        groups = self.groups([{
            "id": "front", "nome": "Capa", "componentes": [{"componente_id": 10, "papel": "capa"}],
        }])
        self.assertEqual(len(groups), 2)
        self.assertIn("sem arte", groups[1]["pendencia_arte"])

    def test_mixed_miolo_is_not_printed_in_cover_flow(self):
        groups = self.groups([{
            "id": "mixed", "nome": "Capa e miolo", "componentes": [
                {"componente_id": 10, "papel": "capa"}, {"componente_id": 30, "papel": "miolo"},
            ],
        }])
        self.assertIn("miolo", groups[0]["pendencia_arte"])

    def test_equal_legacy_confirmations_are_credited_once(self):
        credit, review = legacy_credit(
            [10, 20], "art-1", Decimal(5), {10: {"art-1"}, 20: {"art-1"}},
            {"10|estatica": 5, "20|estatica": 5}, {"10|estatica", "20|estatica"},
        )
        self.assertEqual(credit, 5)
        self.assertFalse(review)

    def test_unequal_legacy_confirmations_require_review(self):
        credit, review = legacy_credit(
            [10, 20], "art-1", Decimal(5), {10: {"art-1"}, 20: {"art-1"}},
            {"10|estatica": 5, "20|estatica": 0}, {"10|estatica"},
        )
        self.assertEqual(credit, 0)
        self.assertTrue(review)


if __name__ == "__main__":
    unittest.main()
