import csv
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import requests

from crawler import content_classification, news_scheduler
from crawler import spotify
from app.api.main import _collection_coverage_days


class LivePhase2Tests(unittest.TestCase):
    def test_daily_scheduler_stops_at_review_gate_and_preserves_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, interim = root / "raw", root / "interim"
            raw.mkdir(); interim.mkdir()
            snapshot = root / "analysis-snapshot.json"
            snapshot.write_text('{"version":"frozen"}', encoding="utf-8")
            checkpoint = raw / "web" / "live_checkpoint.json"
            status = raw / "live_update_status.json"
            coverage = raw / "collection_coverage.jsonl"
            lock = raw / "live_update.lock"

            def discovery(**_kwargs):
                (interim / "web_live_search_report.json").write_text('{"errors":0}', encoding="utf-8")

            def crawl(**_kwargs):
                (interim / "web_live_crawl_report.json").write_text('{"errors":0}', encoding="utf-8")

            def normalize(**_kwargs):
                (interim / "web_live_quality_report.json").write_text('{"clean":2,"review":3,"rejected":1}', encoding="utf-8")

            with patch.object(news_scheduler, "RAW_DIR", raw), patch.object(news_scheduler, "CHECKPOINT", checkpoint), patch.object(news_scheduler, "STATUS_PATH", status), patch.object(news_scheduler, "COVERAGE_PATH", coverage), patch.object(news_scheduler, "LOCK_PATH", lock), patch.object(news_scheduler.web, "INTERIM_DIR", interim), patch.object(news_scheduler.web, "discover", side_effect=discovery), patch.object(news_scheduler.web, "crawl", side_effect=crawl), patch.object(news_scheduler.web_clean, "clean", side_effect=normalize), patch.object(news_scheduler, "_youtube_batch", return_value={"status":"ok","errors":0,"checkpoint_advanced":True}), patch.object(news_scheduler.documents, "build_live"), patch.object(news_scheduler.content_classification, "classify_pending", return_value={"status":"not_configured"}), patch.object(news_scheduler, "read_seeds", return_value=[]):
                result = news_scheduler.run_once(date_from="2026-11-25", date_to="2026-11-25")
            saved = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "awaiting_review")
            self.assertEqual(saved["steps"]["relation_review"]["pending"], 3)
            self.assertEqual(saved["steps"]["import_approved"]["status"], "manual_step_required")
            self.assertEqual(json.loads(checkpoint.read_text(encoding="utf-8"))["last_successful_through"], "2026-11-25")
            self.assertTrue(json.loads(coverage.read_text(encoding="utf-8"))["complete"])
            self.assertEqual(snapshot.read_text(encoding="utf-8"), '{"version":"frozen"}')

    def test_daily_source_without_youtube_key_is_not_counted_as_complete_coverage(self):
        with patch.dict(os.environ, {}, clear=True):
            result = news_scheduler._youtube_batch()
        self.assertEqual(result["status"], "skipped_no_api_key")
        self.assertFalse(result["checkpoint_advanced"])

    def test_spotify_budget_blocks_before_making_an_api_request(self):
        client = spotify.SpotifyClient("id", "secret")
        client.max_calls = 0
        with patch("crawler.spotify.get_json") as request:
            with self.assertRaisesRegex(RuntimeError, "ngân sách"):
                client.get("/search", {"q": "test"})
        request.assert_not_called()

    def test_coverage_ledger_counts_successful_empty_day_but_not_failed_day(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            ledger = raw / "collection_coverage.jsonl"
            with patch.object(news_scheduler, "COVERAGE_PATH", ledger):
                news_scheduler._record_coverage(date(2026, 11, 1), date(2026, 11, 2), False, {"web": "partial"})
                news_scheduler._record_coverage(date(2026, 11, 1), date(2026, 11, 1), True, {"web": "ok", "youtube": "ok"})
            with patch("app.api.main.RAW_DIR", raw):
                covered = _collection_coverage_days(date(2026, 11, 1), date(2026, 11, 3))
            self.assertEqual(covered, {"2026-11-01"})
            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)

    def test_classifier_is_idempotent_by_content_hash_and_model_and_keeps_failures_unlabeled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, status = root / "classifications.csv", root / "status.json"
            doc = {"document_id": "DOC_1", "title": "Tin nhạc", "url": "https://example.org/a", "source": "Nguồn", "published_at": "2026-11-01", "content": "Nghệ sĩ A hợp tác cùng nghệ sĩ B."}
            response = unittest.mock.Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = {"model": "model-v1", "choices": [{"message": {"content": json.dumps({"topics": ["hợp tác"], "sentiment": "chưa xác định", "quote": "Nghệ sĩ A hợp tác cùng nghệ sĩ B."}, ensure_ascii=False)}}]}
            env = {"OPENAI_API_KEY": "test-key", "OPENROUTER_MODEL": "model-v1"}
            with patch.object(content_classification, "OUTPUT", output), patch.object(content_classification, "STATUS", status), patch.object(content_classification, "RAW_DIR", root), patch.object(content_classification, "_input_documents", return_value=[doc]), patch.dict(os.environ, env, clear=True), patch("crawler.content_classification.requests.post", return_value=response) as post:
                first = content_classification.classify_pending(limit=1)
                second = content_classification.classify_pending(limit=1)
                self.assertEqual(first["classified"], 1)
                self.assertEqual(second["status"], "ok")
                self.assertEqual(post.call_count, 1)

                doc["content"] = "Nội dung mới cần thử lại."
                with patch("crawler.content_classification.requests.post", side_effect=requests.ConnectionError("offline")):
                    failed = content_classification.classify_pending(limit=1)
                self.assertEqual(failed["failed"], 1)
                with output.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(rows[-1]["status"], "error")
                self.assertEqual(rows[-1]["sentiment"], "")
                self.assertEqual(rows[-1]["topics"], "")

    def test_missing_classifier_credentials_are_reported_without_a_model_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(content_classification, "OUTPUT", root / "classes.csv"), patch.object(content_classification, "STATUS", root / "status.json"), patch.object(content_classification, "RAW_DIR", root), patch.object(content_classification, "_input_documents", return_value=[{"document_id": "D1", "content": "Some text"}]), patch.dict(os.environ, {}, clear=True), patch("crawler.content_classification.requests.post") as post:
                result = content_classification.classify_pending(limit=1)
            self.assertEqual(result["status"], "not_configured")
            post.assert_not_called()
            self.assertFalse((root / "classes.csv").exists())


if __name__ == "__main__":
    unittest.main()
