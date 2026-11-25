import unittest

from app.api.main import _alert_stats, _trend_stats


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


if __name__ == "__main__":
    unittest.main()
