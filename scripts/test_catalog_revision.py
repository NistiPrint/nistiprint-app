import unittest

from revise_catalog_import import page_counts, sheet_and_ink


class RevisionTests(unittest.TestCase):
    def test_pages_are_not_finished_sheets(self):
        self.assertEqual(page_counts('200 páginas = 100 folhas / em papel offset 75 g'), {200})
        self.assertEqual(page_counts('180 páginas = 90 folhas / em papel offset 75 g'), {180})

    def test_rounds_up_and_uses_manual_ink_rate(self):
        self.assertEqual(sheet_and_ink(210), (53, .901))
        self.assertEqual(sheet_and_ink(204), (51, .867))
        self.assertEqual(sheet_and_ink(393), (99, 1.683))

    def test_does_not_sum_internal_sections(self):
        self.assertEqual(page_counts('280 páginas destinadas para registro. Páginas: 284'), {284})
        self.assertEqual(page_counts('160 páginas (80 folhas), sendo 52 páginas de atividades e 108 páginas de caligrafia.'), {160})

    def test_kit_page_totals_remain_separate(self):
        self.assertEqual(page_counts('Páginas do planner: 210 - Páginas do livro: 40'), {210, 40})


if __name__ == '__main__':
    unittest.main()
