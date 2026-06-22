import unittest

from nistiprint_shared.services.personalized_classification_service import (
    classify_items,
    item_indicates_personalized,
    normalize_personalization_text,
)


class TestPersonalizedClassificationService(unittest.TestCase):
    def test_normalize_removes_accents_and_lowercases(self):
        self.assertEqual(
            normalize_personalization_text("Vacinação PERSONALIZADA"),
            "vacinacao personalizada",
        )

    def test_item_description_indicates_personalized(self):
        self.assertTrue(
            item_indicates_personalized({
                "descricao": "Caderneta de Vacinação Menina Personalizado C/ Nome",
            })
        )

    def test_product_name_indicates_personalized(self):
        self.assertTrue(
            item_indicates_personalized({
                "descricao": "Agenda 2026",
                "produto": {"nome": "Planner Personalizado"},
            })
        )

    def test_plain_item_is_not_personalized(self):
        self.assertFalse(item_indicates_personalized({"descricao": "Caneta simples"}))

    def test_classify_items_returns_matched_indices(self):
        result = classify_items([
            {"descricao": "Caneta simples"},
            {"descricao": "Planner personalizado", "id": 123},
        ])

        self.assertTrue(result.is_personalized)
        self.assertEqual([match.index for match in result.matched_items], [1])
        self.assertEqual(result.matched_items[0].bling_item_id, 123)


if __name__ == "__main__":
    unittest.main()
