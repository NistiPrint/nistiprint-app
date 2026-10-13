import unittest
from datetime import date
from unittest.mock import patch

from nistiprint_shared.services.priority_calculation_service import PriorityCalculationService
from nistiprint_shared.services.priority_calculation_service import supabase_db


class PriorityCalculationExplanationTest(unittest.TestCase):
    def test_snapshot_reproduces_score_at_captured_reference_date(self):
        service = PriorityCalculationService()
        demand = {
            "categoria_temporal": "urgente", "modalidade_logistica": "EXPRESS",
            "data_entrega": "2026-10-10", "classificacao_cliente": "B2B",
            "categoria_demanda": "corporate", "is_flex": True,
            "manual_priority_score": 15, "tipo_demanda": "B2B",
        }
        snapshot = service.explain_priority_score(demand, reference_date=date(2026, 10, 9))
        reproduced = service.calculate_priority_score(
            snapshot["inputs"]["demand"],
            snapshot["inputs"]["item"],
            snapshot["inputs"]["channel"],
            reference_date=date.fromisoformat(snapshot["reference_date"]),
        )

        self.assertEqual(snapshot["rules_revision"], "priority-rules-v1")
        self.assertEqual(reproduced, snapshot["score"])

    def test_score_snapshot_key_is_stable_and_preserves_internal_links(self):
        service = PriorityCalculationService()
        explanation = service.explain_priority_score(
            {"categoria_temporal": "urgente"}, reference_date=date(2026, 10, 9)
        )
        snapshot = service.build_score_snapshot(41, explanation, 82)
        repeated = service.build_score_snapshot(41, explanation, 82)
        changed_link = service.build_score_snapshot(41, explanation, 83)

        self.assertEqual(snapshot["snapshot_key"], repeated["snapshot_key"])
        self.assertNotEqual(snapshot["snapshot_key"], changed_link["snapshot_key"])
        self.assertEqual(snapshot["demand_id"], 41)
        self.assertEqual(snapshot["item_id"], 82)

    def test_persists_snapshots_in_one_idempotent_upsert(self):
        service = PriorityCalculationService()
        with patch.object(supabase_db, "table") as table:
            service.persist_score_snapshots([{"snapshot_key": "stable"}])
        table.assert_called_once_with("priority_score_snapshots")
        table.return_value.upsert.assert_called_once_with(
            [{"snapshot_key": "stable"}],
            on_conflict="snapshot_key", ignore_duplicates=True,
        )


if __name__ == "__main__":
    unittest.main()
