import unittest

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.api.main import _alert_stats, _compare_period, _day_in_period, _trend_stats, update_status


class ApiMetricTests(unittest.TestCase):
    def test_alert_counts_unique_documents_and_never_claims_without_history(self):
        baseline = {f"2026-10-{day:02d}": 0 for day in range(1, 29)}
        current = [
            {"document_id": "D1", "day": "2026-11-01"},
            {"document_id": "D1", "day": "2026-11-01"},
            {"document_id": "D2", "day": "2026-11-02"},
        ]
        incomplete = _alert_stats(baseline, current, history_complete=False)
        self.assertEqual(incomplete["count_7d"], 2)
        self.assertFalse(incomplete["anomaly"])
        self.assertTrue(incomplete["requires_more_history"])
        self.assertEqual(len(incomplete["current_documents"]), 2)

    def test_alert_zero_variance_is_not_reported_as_spike(self):
        baseline = {f"2026-10-{day:02d}": 0 for day in range(1, 29)}
        result = _alert_stats(baseline, [{"document_id": "D1"}], history_complete=True)
        self.assertIsNone(result["z_score"])
        self.assertFalse(result["anomaly"])
        self.assertTrue(result["requires_more_history"])

    def test_trend_aggregation_counts_each_filtered_document_once(self):
        rows = [
            {"document_id": "D1", "day": "2026-11-01", "entities": ["A", "A", "B"]},
            {"document_id": "D1", "day": "2026-11-01", "entities": ["A"]},
            {"document_id": "D2", "day": "2026-11-01", "entities": ["A"]},
            {"document_id": "D3", "day": "2026-11-02", "entities": ["B"]},
        ]
        result = _trend_stats(rows, 30)
        self.assertEqual(result["total_documents"], 3)
        self.assertEqual(result["daily"], [{"date": "2026-11-01", "documents": 2}, {"date": "2026-11-02", "documents": 1}])
        counts = {row["name"]: row["documents"] for row in result["top_entities"]}
        self.assertEqual(counts, {"A": 2, "B": 2})

    def test_entity_counts_use_ids_even_when_names_are_identical(self):
        result = _trend_stats([
            {"document_id": "D1", "day": "2026-11-01", "entities": [{"id": "PER_1", "name": "Linh"}, {"id": "PER_2", "name": "Linh"}]},
            {"document_id": "D1", "day": "2026-11-01", "entities": [{"id": "PER_1", "name": "Linh"}]},
        ], 7)
        self.assertEqual({item["id"]: item["documents"] for item in result["top_entities"]}, {"PER_1": 1, "PER_2": 1})

    def test_zero_baseline_and_unknown_coverage_have_distinct_labels(self):
        self.assertEqual(_compare_period(3, 0, True)["comparison"], "new")
        self.assertIsNone(_compare_period(3, 0, True)["change_percent"])
        self.assertEqual(_compare_period(3, 2, False)["comparison"], "incomplete_coverage")
        self.assertIsNone(_compare_period(3, 2, False)["change_percent"])

    def test_future_and_invalid_publication_dates_are_outside_the_period(self):
        start, end = date(2026, 11, 1), date(2026, 11, 8)
        self.assertTrue(_day_in_period("2026-11-07", start, end))
        self.assertFalse(_day_in_period("2026-11-08", start, end))
        self.assertFalse(_day_in_period("not-a-date", start, end))

    def test_update_status_distinguishes_not_run_from_preserved_snapshot(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("app.api.main.RAW_DIR", root / "raw"), patch("app.api.main.INTERIM_DIR", root / "interim"):
                result = update_status()
        self.assertEqual(result["pipeline"]["status"], "not_run")
        self.assertEqual({source: row["status"] for source, row in result["sources"].items()}, {"web": "not_run", "youtube": "not_run", "spotify": "not_run"})
        self.assertEqual(result["pipeline"]["steps"]["research_snapshot"]["status"], "preserved")
        self.assertEqual(result["pipeline"]["steps"]["content_classification"]["status"], "not_configured")


if __name__ == "__main__":
    unittest.main()
