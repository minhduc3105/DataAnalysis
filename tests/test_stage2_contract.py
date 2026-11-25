import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler import retrieval, stage2
from crawler.model_contract import ModelClient, SCHEMA_VERSION, validate_extraction


class Stage2ContractTests(unittest.TestCase):
    def test_link_rerun_preserves_unchanged_human_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "relation_review.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["document_id", "head_mention_id", "relation_type", "tail_mention_id", "evidence", "decision", "reviewed_by", "reviewed_at", "decision_note"])
                writer.writeheader()
                writer.writerow({"document_id": "D1", "head_mention_id": "m1", "relation_type": "PERFORMED", "tail_mention_id": "m2", "evidence": "literal quote", "decision": "accepted", "reviewed_by": "Đức", "reviewed_at": "2026-11-25T10:00:00+07:00", "decision_note": "Nguồn gốc xác nhận"})
            rows = [{"document_id": "D1", "head_mention_id": "m1", "relation_type": "PERFORMED", "tail_mention_id": "m2", "evidence": "literal quote", "decision": "", "reviewed_by": "", "reviewed_at": "", "decision_note": ""}]
            stage2._preserve_review_fields(rows, path, ("document_id", "head_mention_id", "relation_type", "tail_mention_id", "evidence"))
            self.assertEqual(rows[0]["decision"], "accepted")
            self.assertEqual(rows[0]["reviewed_by"], "Đức")
            self.assertEqual(rows[0]["decision_note"], "Nguồn gốc xác nhận")

    def test_research_snapshot_cutoff_and_duplicate_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "articles.csv"
            rows = [
                {"document_id": "A", "url": "https://news.test/story?utm=a", "source_name": "News", "published_at": "2026-10-21"},
                {"document_id": "B", "url": "https://news.test/story/", "source_name": "News", "published_at": "2026-10-20"},
                {"document_id": "LIVE", "url": "https://news.test/live", "source_name": "News", "published_at": "2026-10-22"},
                {"document_id": "BAD_DATE", "url": "https://news.test/bad", "source_name": "News", "published_at": "unknown"},
            ]
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            with patch.object(stage2, "READY", path):
                selected, audit, date_review = stage2._snapshot_rows()
            self.assertEqual([r["document_id"] for r in selected], ["A"])
            self.assertEqual(audit["rejected_rows"]["trùng document_id hoặc URL chuẩn hóa"], 1)
            self.assertEqual(audit["rejected_rows"]["ngoài kỳ nghiên cứu"], 1)
            self.assertEqual(audit["rejected_rows"]["ngày đăng thiếu/không hợp lệ"], 1)
            self.assertEqual(len(date_review), 1)

    def test_freeze_is_repeatable_and_new_content_creates_new_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            articles = root / "articles.csv"
            entities = root / "entities.csv"
            relations = root / "relations.csv"
            evidence = root / "evidence.csv"
            decisions = root / "decisions.csv"
            candidates = root / "candidates.csv"
            doc_entities = root / "document_entities.csv"
            excluded = root / "excluded.csv"
            def write(path, rows):
                with path.open("w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["document_id"])
                    writer.writeheader()
                    writer.writerows(rows)
            write(articles, [{"document_id": "A", "url": "https://news.test/a", "source_name": "News", "published_at": "2020-01-01", "body_text": "text"}])
            write(entities, [{"entity_id": "PER_1", "entity_type": "Person", "canonical_name": "Artist"}])
            write(relations, [{"relation_id": "R1"}])
            write(evidence, [{"evidence_id": "E1"}])
            for path in (decisions, candidates, doc_entities, excluded):
                write(path, [])
            with (
                patch.object(stage2, "READY", articles),
                patch.object(stage2, "ENTITIES", entities),
                patch.object(stage2, "RELATIONS", relations),
                patch.object(stage2, "EVIDENCE", evidence),
                patch.object(stage2, "DECISIONS", decisions),
                patch.object(stage2, "CANDIDATES", candidates),
                patch.object(stage2, "DOC_ENTITIES", doc_entities),
                patch.object(stage2, "EXCLUDED", excluded),
                patch.object(stage2, "SNAPSHOT_ROOT", root / "snapshots"),
                patch.object(stage2, "_baseline", return_value=([{"relation_id": "R1"}], [])),
            ):
                first = stage2.freeze()
                first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(stage2.freeze(), first)
                write(articles, [{"document_id": "A", "url": "https://news.test/a", "source_name": "News", "published_at": "2020-01-01", "body_text": "changed"}])
                second = stage2.freeze()
                self.assertNotEqual(first, second)
                self.assertEqual(json.loads((first / "manifest.json").read_text(encoding="utf-8")), first_manifest)

    def test_contract_checks_types_mentions_direction_and_literal_evidence(self):
        doc_id = "DOC_1"
        source = "Hoàng Thùy Linh trình bày bài See Tình."
        valid = {
            "document_id": doc_id,
            "schema_version": SCHEMA_VERSION,
            "model_version": "fixture-model",
            "entities": [
                {"mention_id": "p1", "text": "Hoàng Thùy Linh", "type": "Person"},
                {"mention_id": "s1", "text": "See Tình", "type": "Song"},
            ],
            "relations": [{"head_mention_id": "p1", "type": "PERFORMED", "tail_mention_id": "s1", "evidence": "Hoàng Thùy Linh trình bày bài See Tình", "confidence": 0.9}],
        }
        self.assertEqual(validate_extraction(valid, {doc_id: source}), [])
        wrong = json.loads(json.dumps(valid))
        wrong["relations"][0].update(type="TRACK_OF", evidence="Câu không tồn tại")
        errors = validate_extraction(wrong, {doc_id: source})
        self.assertTrue(any("sai hướng" in error for error in errors))
        self.assertTrue(any("không có trong văn bản" in error for error in errors))

    def test_fixture_requires_synthetic_text_and_stays_out_of_real_documents(self):
        fixture = {
            "document_id": "FIXTURE_1", "schema_version": SCHEMA_VERSION, "model_version": "test", "is_fixture": True,
            "fixture_text": "A trình bày bài B.",
            "entities": [{"mention_id": "a", "text": "A", "type": "Person"}, {"mention_id": "b", "text": "B", "type": "Song"}],
            "relations": [{"head_mention_id": "a", "type": "PERFORMED", "tail_mention_id": "b", "evidence": "A trình bày bài B", "confidence": 0.5}],
        }
        self.assertEqual(validate_extraction(fixture, {"FIXTURE_1": fixture["fixture_text"]}), [])
        fixture["fixture_text"] = ""
        self.assertTrue(any("fixture_text" in error for error in validate_extraction(fixture, {"FIXTURE_1": ""})))

    def test_validate_file_accepts_fixture_only_with_fixture_text(self):
        fixture = {
            "document_id": "FIXTURE_1", "schema_version": SCHEMA_VERSION, "model_version": "test", "is_fixture": True,
            "fixture_text": "A trình bày bài B.",
            "entities": [{"mention_id": "a", "text": "A", "type": "Person"}, {"mention_id": "b", "text": "B", "type": "Song"}],
            "relations": [{"head_mention_id": "a", "type": "PERFORMED", "tail_mention_id": "b", "evidence": "A trình bày bài B", "confidence": 0.5}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            extraction_path = Path(tmp) / "extractions.jsonl"
            extraction_path.write_text(json.dumps(fixture) + "\n", encoding="utf-8")
            with patch.object(stage2, "EXTRACTIONS", extraction_path), patch.object(stage2, "MODEL_DIR", Path(tmp)), patch.object(stage2, "_documents_by_id", return_value={}):
                self.assertEqual(stage2.validate_file(extraction_path), 0)
                fixture["fixture_text"] = ""
                extraction_path.write_text(json.dumps(fixture) + "\n", encoding="utf-8")
                self.assertEqual(stage2.validate_file(extraction_path), 1)

    def test_embedding_client_rejects_inconsistent_dimensions(self):
        client = ModelClient(base_url="http://example.test")
        with patch.object(client, "post", return_value={"model_version": "embed-v1", "dimensions": 3, "vectors": [[0.1, 0.2]]}):
            with self.assertRaisesRegex(Exception, "không đồng nhất"):
                client.embed(["x"])

    def test_graph_retrieval_caps_hops_and_filters_evidence_dates(self):
        class Record:
            def __init__(self, values):
                self.values = values
            def data(self):
                return self.values

        class Session:
            def __init__(self):
                self.path_query = ""
            def run(self, query, **params):
                if "RETURN n.entity_id AS id" in query:
                    return [Record({"id": "PER_1", "name": "Artist", "pagerank": 0.8})]
                if "RETURN [n IN nodes(p)" in query:
                    self.path_query = query
                    self.path_params = params
                    return [Record({"nodes": [{"id": "PER_1", "name": "Artist", "type": "Person", "pagerank": 0.8}, {"id": "PER_2", "name": "Partner", "type": "Person", "pagerank": 0.2}], "edges": [{"relation": "COLLABORATED_WITH", "relation_id": "R1", "source": "PER_1", "target": "PER_2"}]})]
                if "RETURN rid AS relation_id" in query:
                    self.evidence_params = params
                    return [Record({"relation_id": "R1", "evidence_id": "E1", "quote": "A and B worked together", "published_at": "2024-01-01"})]
                raise AssertionError(query)

        session = Session()
        result = retrieval.retrieve_graph(session, "Artist", max_hops=8, date_from="2024-01-01", date_to="2024-12-31")
        self.assertEqual(result["status"], "ok")
        self.assertIn("*1..3]", session.path_query)
        self.assertIn("EXISTS {", session.path_query)
        self.assertEqual(session.path_params["date_from"], "2024-01-01")
        self.assertEqual(session.evidence_params["date_to"], "2024-12-31")
        self.assertTrue(result["items"][0]["has_evidence"])

    def test_answer_rejects_model_citations_outside_retrieved_context(self):
        bundle = {"method": "vector", "status": "ok", "items": [{"evidence_id": "E1", "quote": "Evidence sentence", "url": "https://news.test/a", "title": "Story"}]}
        client = ModelClient(base_url="http://model.test")
        with patch.object(retrieval, "ModelClient", return_value=client), patch.object(client, "post", return_value={"schema_version": SCHEMA_VERSION, "model_version": "model-v1", "answer": "Supported answer", "source_ids": ["OTHER"]}):
            result = retrieval.answer("Question", bundle, "vector")
        self.assertEqual(result["status"], "invalid_citations")
        self.assertEqual(result["source_ids"], [])

    def test_answer_returns_only_valid_citations(self):
        bundle = {"method": "vector", "status": "ok", "items": [{"evidence_id": "E1", "quote": "Evidence sentence", "url": "https://news.test/a", "title": "Story"}]}
        client = ModelClient(base_url="http://model.test")
        response = {"schema_version": SCHEMA_VERSION, "model_version": "model-v1", "answer": "Supported answer", "source_ids": ["E1", "OTHER", "E1"]}
        with patch.object(retrieval, "ModelClient", return_value=client), patch.object(client, "post", return_value=response):
            result = retrieval.answer("Question", bundle, "vector")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source_ids"], ["E1"])
        self.assertEqual(len(result["sources"]), 1)


if __name__ == "__main__":
    unittest.main()
