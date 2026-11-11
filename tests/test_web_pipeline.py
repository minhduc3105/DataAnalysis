import csv
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler import web_pipeline, web_signals


class WebPipelineTests(unittest.TestCase):
    def test_atomic_csv_preserves_multiline_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "articles.csv"
            rows = [{"document_id": "DOC_1", "content": "paragraph one\nparagraph two, with comma"}]
            web_pipeline._atomic_csv(path, rows, ["document_id", "content"])
            with path.open(encoding="utf-8-sig", newline="") as f:
                read = list(csv.DictReader(f))
            self.assertEqual(read, rows)

    def test_crawl_batch_rewrite_preserves_legacy_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs_path = root / "raw.csv"
            legacy_web_dir = root / "web"
            legacy_web_dir.mkdir()
            with docs_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=web_pipeline.web.DOC_COLUMNS + ["legacy_note"])
                writer.writeheader()
                writer.writerow({"document_id": "DOC_OLD", "url": "https://example.test/old", "legacy_note": "keep me"})
            with (
                patch.object(web_pipeline.web, "DOCS_PATH", docs_path),
                patch.object(web_pipeline.web, "WEB_DIR", legacy_web_dir),
            ):
                web_pipeline.web._save_docs([{"document_id": "DOC_NEW", "url": "https://example.test/new"}])
            with docs_path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["legacy_note"], "keep me")
            self.assertEqual({r["document_id"] for r in rows}, {"DOC_OLD", "DOC_NEW"})

    def test_canonical_url_resolution_and_validation(self):
        html = '<html><head><link rel="canonical" href="/story/123"></head></html>'
        self.assertEqual(
            web_pipeline._canonical_from_html(html, "https://news.example/a"),
            "https://news.example/story/123",
        )

    def test_relation_surface_search_finds_all_catalog_entities_in_sentence(self):
        surfaces = ["Ca sĩ A", "Nhạc sĩ B"]
        pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(x) for x in surfaces) + r")(?!\w)", re.I)
        owners = {"ca sĩ a": {"PER_A"}, "nhạc sĩ b": {"PER_B"}}
        # The queue may name only one seed; sentence matching still finds both.
        self.assertEqual(web_signals._surface_candidates("Ca sĩ A hợp tác với Nhạc sĩ B", pattern, owners), ["PER_A", "PER_B"])
        self.assertEqual(
            web_pipeline._canonical_from_html('<link rel="canonical" href="javascript:alert(1)">', "https://a.example/"),
            "",
        )

    def test_graph_exports_only_accepted_signals_with_current_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = {"entity_id": "PER_1", "entity_type": "Person", "canonical_name": "A", "verification_status": "đã xác minh"}
            b = {"entity_id": "PER_2", "entity_type": "Person", "canonical_name": "B", "verification_status": "đã xác minh"}
            doc = {"document_id": "DOC_WEB_1", "url": "https://example.test/a", "title": "A và B", "body_text": "A hợp tác với B.", "content_hash": "hash-1", "published_at": "2024-01-01"}
            signal = {"signal_id": "SIG_1", "document_id": doc["document_id"], "entity_a_id": "PER_1", "entity_b_id": "PER_2", "relation_type": "COLLABORATED_WITH", "review_status": "accepted", "document_content_hash": "hash-1", "decision_content_hash": "hash-1", "quote": "A hợp tác với B.", "url": doc["url"], "sentence_location": "câu 1"}
            stale = {**signal, "signal_id": "SIG_2", "document_content_hash": "old-hash"}
            with (
                patch.object(web_pipeline, "READY", root / "ready.csv"),
                patch.object(web_pipeline, "SIGNALS", root / "signals.csv"),
                patch.object(web_pipeline, "GRAPH_DIR", root / "graph"),
                patch.object(web_pipeline, "GRAPH_REPORT", root / "graph_report.json"),
                patch.object(web_pipeline, "_entity_catalog", return_value={"PER_1": a, "PER_2": b}),
            ):
                web_pipeline._atomic_csv(web_pipeline.READY, [doc], ["document_id", "url", "title", "body_text", "content_hash", "published_at"])
                web_pipeline._atomic_csv(web_pipeline.SIGNALS, [signal, stale], list(dict.fromkeys(signal.keys())))
                report = web_pipeline.build_graph()
                with (root / "graph" / "relations.csv").open(encoding="utf-8-sig", newline="") as f:
                    relations = list(csv.DictReader(f))
                with (root / "graph" / "evidence.csv").open(encoding="utf-8-sig", newline="") as f:
                    evidence = list(csv.DictReader(f))
            self.assertEqual(report["relations"], 1)
            self.assertEqual(report["evidence"], 1)
            self.assertEqual(len(relations), 1)
            self.assertEqual(len(evidence), 1)

    def test_apply_decisions_requires_current_hash_and_reviewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            signals = [{"signal_id": "SIG_1", "document_content_hash": "hash-1", "review_status": "unreviewed"}]
            decisions = [{"signal_id": "SIG_1", "review_status": "accepted", "decision_reason": "Bài khẳng định quan hệ", "reviewed_by": "reviewer", "candidate_content_hash": "hash-1", "decision_content_hash": ""}]
            with (
                patch.object(web_pipeline, "SIGNALS", root / "signals.csv"),
                patch.object(web_pipeline, "REVIEW_DECISIONS", root / "decisions.csv"),
            ):
                web_pipeline._atomic_csv(web_pipeline.SIGNALS, signals, list(signals[0]))
                web_pipeline._atomic_csv(web_pipeline.REVIEW_DECISIONS, decisions, web_pipeline.DECISION_COLUMNS)
                result = web_pipeline.apply_decisions()
                applied = web_pipeline._read_csv(web_pipeline.SIGNALS)[0]
            self.assertEqual(result["applied_decisions"], 1)
            self.assertEqual(applied["decision_content_hash"], "hash-1")


if __name__ == "__main__":
    unittest.main()
