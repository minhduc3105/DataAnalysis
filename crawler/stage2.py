"""Data snapshots, model handoff, extraction review, and idempotent graph enrichment."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

from .common import normalize_name, now_iso
from .config import INTERIM_DIR, ROOT
from .graphdb import connect
from .model_contract import ModelClient, RELATION_SIGNATURES, SCHEMA_VERSION, UNDIRECTED, validate_extraction

READY = ROOT / "data/processed/web/articles_ready.csv"
LIVE_READY = INTERIM_DIR / "web_live_documents.csv"
LIVE_YOUTUBE = INTERIM_DIR / "live_documents.csv"
EXCLUDED = ROOT / "data/processed/web/articles_excluded.csv"
ENTITIES = ROOT / "data/interim/graph/entities.csv"
RELATIONS = ROOT / "data/interim/graph/relations.csv"
EVIDENCE = ROOT / "data/interim/graph/evidence.csv"
DOC_ENTITIES = ROOT / "data/processed/web/document_entities.csv"
DECISIONS = ROOT / "data/processed/web/relation_decisions.csv"
CANDIDATES = ROOT / "data/processed/web/relation_candidates.csv"
MODEL_DIR = INTERIM_DIR / "model_handoff"
SNAPSHOT_ROOT = ROOT / "data/snapshots"
EXTRACTIONS = MODEL_DIR / "extractions.jsonl"
LINK_REVIEW = MODEL_DIR / "entity_link_review.csv"
RELATION_REVIEW = MODEL_DIR / "relation_review.csv"
APPROVED_ENTITIES = MODEL_DIR / "approved_entities.csv"
PREFIX = {"Person": "PER", "Group": "GRO", "Song": "SON", "Album": "ALB", "Company": "COM", "Show": "SHO", "Event": "EVT", "Brand": "BRA"}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _preserve_review_fields(rows: list[dict[str, Any]], path: Path, key_fields: tuple[str, ...]) -> None:
    review_fields = ("decision", "reviewed_by", "reviewed_at", "decision_note", "linked_entity_id")
    old_rows = _read_csv(path)
    old_by_key = {tuple(row.get(field, "") for field in key_fields): row for row in old_rows}
    for row in rows:
        old = old_by_key.get(tuple(row.get(field, "") for field in key_fields), {})
        for field in review_fields:
            if old.get(field, "").strip():
                row[field] = old[field]


def _url_key(value: str) -> str:
    p = urlsplit((value or "").strip())
    host = (p.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+", "/", p.path).rstrip("/")
    return urlunsplit((p.scheme.lower(), host, path, "", ""))


def _baseline() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    decisions = {r.get("signal_id", ""): r for r in _read_csv(DECISIONS)}
    candidates = _read_csv(CANDIDATES)
    joined = []
    for row in candidates:
        joined.append({**row, **{f"decision_{k}": v for k, v in decisions.get(row.get("signal_id", ""), {}).items() if k != "signal_id"}})
    return _read_csv(ROOT / "data/processed/web/graph_clean/relations.csv"), joined


def _snapshot_rows() -> tuple[list[dict[str, str]], dict[str, Any], list[dict[str, str]]]:
    rows = _read_csv(READY)
    start, cutoff = date(2016, 1, 1), date(2026, 10, 21)
    selected, rejected, date_review = [], Counter(), []
    ids, urls = set(), set()
    for row in rows:
        conflict = (row.get("published_at_conflict") or row.get("date_conflict") or "").strip()
        published = (row.get("published_at") or row.get("published_at_iso") or "")[:10]
        if conflict:
            rejected["ngày đăng mâu thuẫn"] += 1
            date_review.append({**row, "review_reason": conflict or "metadata ngày đăng mâu thuẫn"})
            continue
        try:
            day = date.fromisoformat(published)
        except ValueError:
            rejected["ngày đăng thiếu/không hợp lệ"] += 1
            date_review.append({**row, "review_reason": "ngày đăng thiếu/không hợp lệ; cần xác minh từ nguồn gốc"})
            continue
        if not start <= day <= cutoff:
            rejected["ngoài kỳ nghiên cứu"] += 1
            continue
        doc_id, url, source = row.get("document_id", "").strip(), (row.get("final_url") or row.get("resolved_url") or row.get("url") or "").strip(), row.get("source_name", "").strip()
        try:
            parsed_url = urlsplit(url)
            valid_url = parsed_url.scheme in {"http", "https"} and bool(parsed_url.hostname)
        except ValueError:
            valid_url = False
        if not doc_id or not url or not source or not valid_url:
            rejected["thiếu document_id/URL/nguồn"] += 1
            continue
        if doc_id in ids or _url_key(url) in urls:
            rejected["trùng document_id hoặc URL chuẩn hóa"] += 1
            continue
        ids.add(doc_id)
        urls.add(_url_key(url))
        row["url"] = url
        row["published_at"] = day.isoformat()
        selected.append(row)
    return selected, {"source_rows": len(rows), "selected_rows": len(selected), "rejected_rows": dict(rejected), "pending_date_review": len(date_review), "date_min": min((r["published_at"][:10] for r in selected), default=""), "date_max": max((r["published_at"][:10] for r in selected), default="")}, date_review


def _snapshot_stats(rows: list[dict[str, str]], date_review: list[dict[str, str]] | None = None) -> dict[str, Any]:
    entity_counts = Counter()
    for row in _read_csv(DOC_ENTITIES):
        entity_counts[row.get("document_id", "")] += 1
    by_source = Counter(r.get("source_name", "") or "không rõ" for r in rows)
    by_month = Counter((r.get("published_at", "")[:7] or "không rõ") for r in rows)
    lengths = [len(r.get("body_text") or r.get("content") or "") for r in rows]
    excluded = Counter((r.get("review_reason") or "không ghi lý do").strip() for r in _read_csv(EXCLUDED))
    return {
        "by_source": dict(sorted(by_source.items())),
        "by_month": dict(sorted(by_month.items())),
        "content_chars": {"mean": round(sum(lengths) / len(lengths), 1) if lengths else 0, "median": int(pd.Series(lengths).median()) if lengths else 0},
        "documents_with_2plus_linked_entities": sum(entity_counts[r["document_id"]] >= 2 for r in rows),
        "share_with_2plus_linked_entities": round(sum(entity_counts[r["document_id"]] >= 2 for r in rows) / len(rows), 4) if rows else 0,
        "excluded_reasons_top50": dict(excluded.most_common(50)),
        "duplicate_content_groups": sum(bool(r.get("duplicate_of") or r.get("duplicate_content_of")) for r in rows),
        "pending_date_review": len(date_review or []),
    }


def _verify_snapshot(target: Path) -> dict[str, Any]:
    manifest_path = target / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Không thấy manifest snapshot: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, metadata in manifest.get("files", {}).items():
        path = target / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != metadata.get("sha256"):
            raise RuntimeError(f"Snapshot sai checksum ở {name}: {target}")
    return manifest


def freeze() -> Path:
    rows, audit, date_review = _snapshot_rows()
    stats = _snapshot_stats(rows, date_review)
    stats_bytes = json.dumps(stats, ensure_ascii=False, indent=2).encode("utf-8")
    csv_bytes = pd.DataFrame(rows).to_csv(index=False, encoding="utf-8-sig").encode("utf-8")
    graph_entities = _read_csv(ENTITIES)
    relation_rows, decision_rows = _baseline()
    entity_bytes = pd.DataFrame(graph_entities).to_csv(index=False, encoding="utf-8-sig").encode("utf-8")
    relation_bytes = pd.DataFrame(relation_rows).to_csv(index=False, encoding="utf-8-sig").encode("utf-8")
    decision_bytes = pd.DataFrame(decision_rows).to_csv(index=False, encoding="utf-8-sig").encode("utf-8")
    review_bytes = pd.DataFrame(date_review).to_csv(index=False, encoding="utf-8-sig").encode("utf-8")
    digest = hashlib.sha256(csv_bytes + entity_bytes + relation_bytes + decision_bytes + review_bytes + stats_bytes).hexdigest()
    version = f"research-2016-01-01_2026-10-21-{digest[:12]}"
    target = SNAPSHOT_ROOT / version
    target.mkdir(parents=True, exist_ok=True)
    expected = {"articles.csv": csv_bytes, "entity_dictionary.csv": entity_bytes, "baseline_graph_relations.csv": relation_bytes, "baseline_relation_decisions.csv": decision_bytes, "date_review.csv": review_bytes, "statistics.json": stats_bytes}
    if (target / "manifest.json").exists():
        existing_manifest = _verify_snapshot(target)
        if existing_manifest.get("snapshot_version") != version:
            raise RuntimeError(f"Tên snapshot và manifest không khớp: {target}")
        for name, content in expected.items():
            path = target / name
            if not path.exists() or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(content).digest():
                raise RuntimeError(f"Snapshot bất biến đã tồn tại nhưng {name} bị thay đổi: {target}")
        print(f"Snapshot đã tồn tại và được xác minh: {version} | {len(rows)} bài | {target}")
        return target
    for name, content in expected.items():
        (target / name).write_bytes(content)
    manifest = {
        "snapshot_version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "period_start": "2016-01-01",
        "period_end": "2026-10-21",
        "schema_version": SCHEMA_VERSION,
        "audit": audit,
        "statistics": stats,
        "files": {name: {"rows": len(rows) if name == "articles.csv" else len(graph_entities) if name == "entity_dictionary.csv" else len(relation_rows) if name == "baseline_graph_relations.csv" else len(decision_rows) if name == "baseline_relation_decisions.csv" else len(date_review) if name == "date_review.csv" else 1, "sha256": hashlib.sha256(content).hexdigest()} for name, content in expected.items()},
        "baseline_graph": {"entities": len(graph_entities), "relations": len(_read_csv(RELATIONS))},
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Snapshot: {version} | {len(rows)} bài | {target}")
    print(f"Kiểm tra ngày/ID/URL: {audit}; ≥2 thực thể: {stats['documents_with_2plus_linked_entities']}")
    return target


def export_handoff(snapshot: str | None = None) -> Path:
    if snapshot:
        target = SNAPSHOT_ROOT / snapshot
    else:
        dirs = sorted(SNAPSHOT_ROOT.glob("research-*"), key=lambda p: json.loads((p / "manifest.json").read_text(encoding="utf-8")).get("created_at", "") if (p / "manifest.json").exists() else "")
        if not dirs:
            target = freeze()
        else:
            target = dirs[-1]
    manifest = _verify_snapshot(target)
    out = ROOT / "data/exports/huy" / manifest["snapshot_version"]
    out.mkdir(parents=True, exist_ok=True)
    for name in ("articles.csv", "entity_dictionary.csv", "baseline_graph_relations.csv", "baseline_relation_decisions.csv", "statistics.json", "manifest.json"):
        (out / name).write_bytes((target / name).read_bytes())
    sample = _read_csv(target / "articles.csv")
    sample.sort(key=lambda r: hashlib.sha256(r["document_id"].encode()).hexdigest())
    _write_csv(out / "sample_20.csv", sample[:20])
    contract = ROOT / "schemas/model_contract_v1.json"
    (out / contract.name).write_bytes(contract.read_bytes())
    print(f"Gói bàn giao Huy: {out}")
    return out


def _documents_by_id() -> dict[str, str]:
    result = {}
    for path in (READY, LIVE_READY, LIVE_YOUTUBE):
        result.update({r.get("document_id", ""): r.get("body_text") or r.get("content") or "" for r in _read_csv(path)})
    return result


def validate_file(path: Path = EXTRACTIONS) -> int:
    documents = _documents_by_id()
    errors, seen = [], set()
    if not path.exists():
        raise FileNotFoundError(f"Chưa có {path}; đặt kết quả Huy vào đây, một JSON object mỗi dòng")
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append({"line": line_no, "document_id": "", "errors": [f"JSON lỗi: {exc.msg}"], "is_fixture": False})
                continue
            if not isinstance(row, dict):
                errors.append({"line": line_no, "document_id": "", "errors": ["Mỗi dòng phải là JSON object"], "is_fixture": False})
                continue
            doc_id = str(row.get("document_id", ""))
            if doc_id in seen:
                msg = ["document_id lặp trong file; giữ đúng một kết quả mỗi văn bản"]
            else:
                msg = []
            seen.add(doc_id)
            if row.get("is_fixture") is True:
                msg += validate_extraction(row, {doc_id: str(row.get("fixture_text", ""))})
            else:
                msg += validate_extraction(row, documents)
            if msg:
                errors.append({"line": line_no, "document_id": doc_id, "errors": msg, "is_fixture": bool(row.get("is_fixture"))})
    path_out = MODEL_DIR / "validation_errors.json"
    path_out.parent.mkdir(parents=True, exist_ok=True)
    path_out.write_text(json.dumps({"checked_at": now_iso(), "rows": len(seen), "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    fixtures = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                fixtures += bool(json.loads(line).get("is_fixture"))
            except json.JSONDecodeError:
                pass
    print(f"Đã kiểm tra {len(seen)} văn bản; lỗi {len(errors)}; fixture {fixtures}. Chi tiết: {path_out}")
    return len(errors)


def _type_inventory() -> tuple[dict[str, dict], dict[tuple[str, str], list[dict]]]:
    by_id = {}
    by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in _read_csv(ENTITIES) + _read_csv(APPROVED_ENTITIES):
        by_id[row["entity_id"]] = row
        for name in [row.get("canonical_name", ""), *re.split(r"[|;,]", row.get("aliases", ""))]:
            key = normalize_name(name)
            if key:
                bucket = by_name[(row.get("entity_type", ""), key)]
                if all(e["entity_id"] != row["entity_id"] for e in bucket):
                    bucket.append(row)
    return by_id, by_name


def _cosine(left: list[float], right: list[float]) -> float:
    denominator = sum(x * x for x in left) ** 0.5 * sum(x * x for x in right) ** 0.5
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


def link(use_embeddings: bool = False) -> tuple[Path, Path]:
    errors = validate_file()
    if errors:
        raise RuntimeError(f"{errors} lỗi hợp đồng; xem {MODEL_DIR / 'validation_errors.json'}")
    _, names = _type_inventory()
    catalog_by_type: dict[str, dict[str, dict]] = defaultdict(dict)
    for (etype, _), rows in names.items():
        for entity in rows:
            catalog_by_type[etype][entity["entity_id"]] = entity
    raw_rows = [json.loads(line) for line in EXTRACTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    raw_rows = [row for row in raw_rows if not row.get("is_fixture")]
    mention_data: dict[tuple[str, str], dict] = {}
    for row in raw_rows:
        for mention in row["entities"]:
            key = (mention["type"], normalize_name(mention["text"]))
            if key not in mention_data:
                exact = names.get(key, [])
                catalog = list(catalog_by_type[mention["type"]].values())
                ranked = sorted(catalog, key=lambda e: SequenceMatcher(None, key[1], normalize_name(e["canonical_name"])).ratio(), reverse=True)
                mention_data[key] = {"text": mention["text"], "exact": exact, "candidates": exact or ranked[:30]}
    embedding_model = ""
    if use_embeddings:
        client = ModelClient(timeout=float(os.getenv("MODEL_API_TIMEOUT", "120")))
        unresolved = [data for data in mention_data.values() if not data["exact"]]
        strings = list(dict.fromkeys([data["text"] for data in unresolved] + [e["canonical_name"] for data in unresolved for e in data["candidates"]]))
        vectors: dict[str, list[float]] = {}
        embedding_dimensions = None
        for start in range(0, len(strings), 64):
            model, dimensions, batch_vectors = client.embed(strings[start:start + 64])
            if embedding_model and embedding_model != model:
                raise RuntimeError("/embed đổi model_version giữa các batch; chưa ghi bảng liên kết")
            if embedding_dimensions is not None and embedding_dimensions != dimensions:
                raise RuntimeError("/embed đổi số chiều giữa các batch; chưa ghi bảng liên kết")
            embedding_model = model
            embedding_dimensions = dimensions
            vectors.update(zip(strings[start:start + 64], batch_vectors))
        for data in mention_data.values():
            exact = data["exact"]
            if exact:
                continue
            candidates = data["candidates"]
            mention_vector = vectors[data["text"]]
            data["candidates"] = sorted(candidates, key=lambda e: _cosine(mention_vector, vectors[e["canonical_name"]]), reverse=True)
    link_rows, relation_rows = [], []
    for row in raw_rows:
        entity_map = {}
        for mention in row["entities"]:
            text, etype = mention["text"], mention["type"]
            data = mention_data[(etype, normalize_name(text))]
            exact = data["exact"]
            candidates = data["candidates"][:3]
            status = "linked_exact" if len(exact) == 1 else "ambiguous" if exact else "pending"
            linked = exact[0]["entity_id"] if len(exact) == 1 else ""
            entity_map[mention["mention_id"]] = {"linked": linked, "type": etype, "text": text}
            link_rows.append({"document_id": row["document_id"], "mention_id": mention["mention_id"], "mention": text, "entity_type": etype, "candidate_entity_ids": "|".join(e["entity_id"] for e in candidates), "candidate_names": "|".join(e["canonical_name"] for e in candidates), "match_status": status, "linked_entity_id": linked, "embedding_model_version": embedding_model, "decision": "", "reviewed_by": "", "reviewed_at": "", "decision_note": ""})
        for relation in row["relations"]:
            head, tail = entity_map[relation["head_mention_id"]], entity_map[relation["tail_mention_id"]]
            relation_rows.append({"document_id": row["document_id"], "model_version": row["model_version"], "head_mention_id": relation["head_mention_id"], "head_text": head["text"], "head_type": head["type"], "head_entity_id": head["linked"], "relation_type": relation["type"], "tail_mention_id": relation["tail_mention_id"], "tail_text": tail["text"], "tail_type": tail["type"], "tail_entity_id": tail["linked"], "evidence": relation["evidence"], "confidence": relation["confidence"], "decision": "", "reviewed_by": "", "reviewed_at": "", "decision_note": ""})
    _preserve_review_fields(link_rows, LINK_REVIEW, ("document_id", "mention_id", "mention", "entity_type"))
    _preserve_review_fields(relation_rows, RELATION_REVIEW, ("document_id", "head_mention_id", "relation_type", "tail_mention_id", "evidence"))
    _write_csv(LINK_REVIEW, link_rows)
    _write_csv(RELATION_REVIEW, relation_rows)
    print(f"Liên kết: {len(link_rows)} mention ({sum(r['match_status']=='linked_exact' for r in link_rows)} khớp duy nhất); {len(relation_rows)} quan hệ cần kiểm tra/duyệt.")
    print(f"Duyệt: {LINK_REVIEW} và {RELATION_REVIEW}; điền decision=accepted/rejected, và linked_entity_id nếu cần.")
    return LINK_REVIEW, RELATION_REVIEW


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_N{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12].upper()}"


def _graph_quality(session) -> dict[str, Any]:
    counts = session.run("""
        CALL { MATCH (n:Entity) RETURN count(n) AS entities, count(DISTINCT n.entity_id) AS distinct_ids }
        CALL { MATCH (a:Entity)-[r]->(b:Entity) RETURN count(r) AS relations }
        CALL {
            MATCH (e:Evidence)
            OPTIONAL MATCH (e)-[:FROM_DOCUMENT]->(d:Document)
            RETURN count(DISTINCT e) AS evidence,
                   count(DISTINCT CASE WHEN d IS NOT NULL THEN e END) AS linked_evidence,
                   count(DISTINCT d) AS evidence_documents
        }
        RETURN entities,distinct_ids,relations,evidence,linked_evidence,evidence_documents
    """).single().data()
    isolated = session.run("MATCH (n:Entity) WHERE NOT (n)--(:Entity) RETURN count(n) AS n").single()["n"]
    supported = session.run("""
        MATCH (a:Entity)-[r]->(b:Entity)
        OPTIONAL MATCH (e:Evidence {relation_id:r.relation_id})
        RETURN count(DISTINCT r.relation_id) AS relations,
               count(DISTINCT CASE WHEN e IS NOT NULL THEN r.relation_id END) AS supported_relations
    """).single().data()
    invalid_schema = 0
    for row in session.run("""
        MATCH (a:Entity)-[r]->(b:Entity)
        RETURN type(r) AS relation,[l IN labels(a) WHERE l<>'Entity'][0] AS source_type,
               [l IN labels(b) WHERE l<>'Entity'][0] AS target_type
    """):
        signature = RELATION_SIGNATURES.get(row["relation"])
        if not signature or (row["source_type"] not in signature[0] or row["target_type"] not in signature[1]):
            if not signature or row["relation"] not in UNDIRECTED or row["target_type"] not in signature[0] or row["source_type"] not in signature[1]:
                invalid_schema += 1
    entities = int(counts["entities"] or 0)
    relations = int(supported["relations"] or 0)
    supported_relations = int(supported["supported_relations"] or 0)
    evidence_count = int(counts["evidence"] or 0)
    linked_evidence = int(counts["linked_evidence"] or 0)
    return {
        "entities": entities,
        "duplicate_entity_ids": entities - int(counts["distinct_ids"] or 0),
        "isolated_entities": int(isolated),
        "relations": relations,
        "schema_invalid_relations": invalid_schema,
        "relations_with_evidence": supported_relations,
        "relation_evidence_coverage": round(supported_relations / relations, 4) if relations else 0,
        "evidence": evidence_count,
        "evidence_linked_to_document": linked_evidence,
        "evidence_document_coverage": round(linked_evidence / evidence_count, 4) if evidence_count else 0,
        "documents_with_evidence": int(counts["evidence_documents"] or 0),
    }


def apply_approved(dry_run: bool = False) -> dict[str, int]:
    if not LINK_REVIEW.exists() or not RELATION_REVIEW.exists():
        raise FileNotFoundError("Chạy `stage2 link` và điền bảng duyệt trước")
    entities, _ = _type_inventory()
    mentions = {(r["document_id"], r["mention_id"]): r for r in _read_csv(LINK_REVIEW)}
    docs = {r.get("document_id", ""): r for path in (READY, LIVE_READY, LIVE_YOUTUBE) for r in _read_csv(path)}
    model_by_doc = {}
    if EXTRACTIONS.exists():
        for line in EXTRACTIONS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if not row.get("is_fixture"):
                    model_by_doc[row["document_id"]] = row["model_version"]
    approved = []
    new_entities = {}
    baseline_relation_ids = {(r["source_entity_id"], r["relation_type"], r["target_entity_id"]): r["relation_id"] for r in _read_csv(RELATIONS)}
    existing_evidence_ids = {}
    for ev in _read_csv(EVIDENCE):
        existing_evidence_ids[(ev.get("relation_id", ""), ev.get("document_id", ""), normalize_name(ev.get("quote", "")))] = ev.get("evidence_id", "")
    rejected = 0
    for row in _read_csv(RELATION_REVIEW):
        if row.get("decision", "").strip().lower() != "accepted":
            rejected += 1
            continue
        reviewer = row.get("reviewed_by", "").strip()
        reviewed_at = row.get("reviewed_at", "").strip()
        if not reviewer:
            raise ValueError(f"Quan hệ được duyệt cần reviewed_by: {row['document_id']} / {row['relation_type']}")
        try:
            timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"reviewed_at phải là ISO-8601 có múi giờ cho {row['document_id']}") from exc
        if timestamp.tzinfo is None:
            raise ValueError(f"reviewed_at phải kèm múi giờ, ví dụ +07:00: {row['document_id']}")
        head = mentions.get((row["document_id"], row["head_mention_id"]), {})
        tail = mentions.get((row["document_id"], row["tail_mention_id"]), {})
        for mention in (head, tail):
            if not mention or mention.get("decision", "").lower() == "rejected":
                raise ValueError(f"Quan hệ được duyệt có mention bị từ chối/thiếu: {row['document_id']}")
            if not mention.get("linked_entity_id") and mention.get("decision", "").lower() == "accepted_new":
                etype = mention["entity_type"]
                entity_id = _stable_id(PREFIX[etype], f"{etype}:{normalize_name(mention['mention'])}")
                mention["linked_entity_id"] = entity_id
                new_entities[entity_id] = {"entity_id": entity_id, "entity_type": etype, "canonical_name": mention["mention"], "aliases": "", "verification_status": "chờ kiểm tra", "notes": "Tạo từ kết quả trích xuất đã duyệt", "seed_id": ""}
        source, target = head.get("linked_entity_id", ""), tail.get("linked_entity_id", "")
        if not source or not target:
            raise ValueError(f"Chưa liên kết đủ hai đầu quan hệ ở {row['document_id']}")
        if source == target:
            raise ValueError("Quan hệ tự nối không hợp lệ")
        if row["relation_type"] not in RELATION_SIGNATURES:
            raise ValueError(f"Relation type không hợp lệ: {row['relation_type']}")
        signature = RELATION_SIGNATURES[row["relation_type"]]
        source_entity = entities.get(source) or new_entities.get(source)
        target_entity = entities.get(target) or new_entities.get(target)
        if source_entity and target_entity and (source_entity["entity_type"] not in signature[0] or target_entity["entity_type"] not in signature[1]):
            if row["relation_type"] not in UNDIRECTED or target_entity["entity_type"] not in signature[0] or source_entity["entity_type"] not in signature[1]:
                raise ValueError(f"Sai hướng/kiểu nút cho {row['relation_type']}: {source_entity['entity_type']}→{target_entity['entity_type']}")
        doc = docs.get(row["document_id"])
        if not doc:
            raise ValueError(f"Không tìm thấy văn bản {row['document_id']}")
        text = doc.get("body_text") or doc.get("content") or ""
        if normalize_name(row.get("evidence", "")) not in normalize_name(text):
            raise ValueError(f"Bằng chứng không khớp văn bản gốc: {row['document_id']}")
        if row["relation_type"] in UNDIRECTED and source > target:
            source, target = target, source
        relation_key = (source, row["relation_type"], target)
        relation_id = baseline_relation_ids.get(relation_key) or "R2_" + hashlib.sha256("|".join(relation_key).encode()).hexdigest()[:20]
        evidence_key = (relation_id, row["document_id"], normalize_name(row["evidence"]))
        evidence_id = existing_evidence_ids.get(evidence_key) or "E2_" + hashlib.sha256("|".join(evidence_key).encode()).hexdigest()[:20]
        model_version = model_by_doc.get(row["document_id"], "unknown")
        review_event_id = "REV_" + hashlib.sha256("|".join((relation_id, evidence_id, reviewer, timestamp.isoformat(), row.get("decision_note", ""))).encode("utf-8")).hexdigest()[:20]
        approved.append({**row, "source_entity_id": source, "target_entity_id": target, "relation_id": relation_id, "evidence_id": evidence_id, "model_version": model_version, "reviewer": reviewer, "reviewed_at": timestamp.isoformat(), "decision_note": row.get("decision_note", ""), "review_event_id": review_event_id, "source_name": head.get("mention", ""), "target_name": tail.get("mention", ""), "document": doc})

    real_extraction_lines = []
    if EXTRACTIONS.exists():
        for line in EXTRACTIONS.read_text(encoding="utf-8").splitlines():
            if line.strip() and not json.loads(line).get("is_fixture"):
                real_extraction_lines.append(line.strip())
    extraction_digest = hashlib.sha256("\n".join(real_extraction_lines).encode("utf-8")).hexdigest() if real_extraction_lines else ""
    report = {"approved_relations": len(approved), "new_entities": len(new_entities), "not_approved": rejected, "model_versions": sorted({r["model_version"] for r in approved}), "schema_version": SCHEMA_VERSION, "extraction_batch_version": extraction_digest[:16], "extraction_sha256": extraction_digest, "review_events": [{"event_id": r["review_event_id"], "document_id": r["document_id"], "relation_id": r["relation_id"], "evidence_id": r["evidence_id"], "reviewer": r["reviewer"], "reviewed_at": r["reviewed_at"], "decision_note": r["decision_note"], "model_version": r["model_version"]} for r in approved], "dry_run": dry_run}
    if dry_run:
        print(f"Dry-run nhập tăng dần: {report}; chưa kết nối hoặc ghi Neo4j")
        return report
    if not approved:
        print("Không có quan hệ được duyệt; không ghi Neo4j.")
        return report
    driver = connect()
    try:
        with driver.session() as session:
            report["quality_before"] = _graph_quality(session)
            required_ids = sorted({r[k] for r in approved for k in ("source_entity_id", "target_entity_id")} - set(new_entities))
            found = {r["id"]: r["entity_type"] for r in session.run("MATCH (n:Entity) WHERE n.entity_id IN $ids RETURN n.entity_id AS id, [l IN labels(n) WHERE l <> 'Entity'][0] AS entity_type", ids=required_ids)}
            found_ids = set(found)
            missing_ids = set(required_ids) - found_ids
            if missing_ids:
                raise ValueError(f"linked_entity_id không tồn tại trong Neo4j: {sorted(missing_ids)[:20]}")
            for row in approved:
                source_type = (entities.get(row["source_entity_id"]) or new_entities.get(row["source_entity_id"]) or {}).get("entity_type") or found.get(row["source_entity_id"])
                target_type = (entities.get(row["target_entity_id"]) or new_entities.get(row["target_entity_id"]) or {}).get("entity_type") or found.get(row["target_entity_id"])
                signature = RELATION_SIGNATURES[row["relation_type"]]
                if source_type not in signature[0] or target_type not in signature[1]:
                    if row["relation_type"] not in UNDIRECTED or target_type not in signature[0] or source_type not in signature[1]:
                        raise ValueError(f"linked_entity_id sai loại cho {row['relation_type']}: {source_type}→{target_type}")
            session.run("CREATE CONSTRAINT stage2_entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE").consume()
            session.run("CREATE CONSTRAINT stage2_document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.document_id IS UNIQUE").consume()
            session.run("CREATE CONSTRAINT stage2_evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.evidence_id IS UNIQUE").consume()
            session.run("CREATE CONSTRAINT stage2_review_event_id IF NOT EXISTS FOR (n:ReviewEvent) REQUIRE n.event_id IS UNIQUE").consume()
            for entity_id, entity in new_entities.items():
                etype = entity["entity_type"]
                session.run(f"MERGE (n:Entity:{etype} {{entity_id: $id}}) ON CREATE SET n.name=$name, n.aliases=[], n.verification_status=$status, n.stage2_created=true", id=entity_id, name=entity["canonical_name"], status=entity["verification_status"]).consume()
            for row in approved:
                doc = row["document"]
                session.run("""
                    MERGE (d:Document {document_id:$docid})
                    ON CREATE SET d.url=$url, d.title=$title, d.source_name=$source, d.published_at=$published, d.platform=$platform, d.content_tag=$tag, d.collected_at=$collected
                    SET d.collected_at=coalesce(d.collected_at,$collected)
                """, docid=doc["document_id"], url=doc.get("final_url") or doc.get("url", ""), title=doc.get("title", ""), source=doc.get("source_name", ""), published=doc.get("published_at", ""), platform=doc.get("platform", "web"), tag=doc.get("content_tag", "press"), collected=doc.get("collected_at") or now_iso()).consume()
                rtype = row["relation_type"]
                session.run(f"""
                    MATCH (a:Entity {{entity_id:$source}}), (b:Entity {{entity_id:$target}})
                    MERGE (a)-[r:{rtype} {{relation_id:$rid}}]->(b)
                    ON CREATE SET r.verification_status='đã xác minh', r.n_documents=0, r.first_year=toInteger(substring($published,0,4)), r.confidence=toFloat($confidence), r.model_version=$model, r.model_versions=[$model], r.stage2=true
                    WITH r,$model AS model
                    SET r.model_versions=CASE WHEN model IN coalesce(r.model_versions,[]) THEN coalesce(r.model_versions,[]) ELSE coalesce(r.model_versions,[])+[model] END
                    WITH r
                    MATCH (d:Document {{document_id:$docid}})
                    MERGE (e:Evidence {{evidence_id:$eid}})
                    ON CREATE SET e.relation_id=$rid, e.quote=$quote, e.sentence_location='', e.extraction_method='SLM:'+$model, e.review_status='accepted', e.confidence_score=toFloat($confidence), e.model_version=$model, e.model_versions=[$model], e.stage2=true
                    WITH r,e,d,$model AS model
                    SET e.model_versions=CASE WHEN model IN coalesce(e.model_versions,[]) THEN coalesce(e.model_versions,[]) ELSE coalesce(e.model_versions,[])+[model] END,e.stage2=true
                    WITH r,e,d,$event AS event
                    MERGE (e)-[:FROM_DOCUMENT]->(d)
                    MERGE (v:ReviewEvent {event_id:event.id})
                    ON CREATE SET v.document_id=event.document_id,v.relation_id=event.relation_id,v.evidence_id=event.evidence_id,v.decision='accepted',v.reviewer=event.reviewer,v.reviewed_at=event.reviewed_at,v.decision_note=event.decision_note,v.model_version=event.model_version,v.schema_version=event.schema_version,v.extraction_batch_version=event.extraction_batch_version,v.source_url=event.source_url,v.source_name=event.source_name
                    MERGE (v)-[:REVIEWS]->(e)
                    WITH r
                    MATCH (x:Evidence {relation_id:$rid})-[:FROM_DOCUMENT]->(source:Document)
                    WITH r,count(DISTINCT source) AS document_count
                    SET r.n_documents=document_count
                """, source=row["source_entity_id"], target=row["target_entity_id"], rid=row["relation_id"], published=doc.get("published_at", ""), confidence=float(row["confidence"]), model=row["model_version"], docid=doc["document_id"], eid=row["evidence_id"], quote=row["evidence"], event={"id": row["review_event_id"], "document_id": doc["document_id"], "relation_id": row["relation_id"], "evidence_id": row["evidence_id"], "reviewer": row["reviewer"], "reviewed_at": row["reviewed_at"], "decision_note": row["decision_note"], "model_version": row["model_version"], "schema_version": SCHEMA_VERSION, "extraction_batch_version": report["extraction_batch_version"], "source_url": doc.get("final_url") or doc.get("url", ""), "source_name": doc.get("source_name", "")}).consume()
            counts = session.run("MATCH (n:Entity) RETURN count(n) AS entities").single().data()
            report["graph_entities_after"] = counts["entities"]
            report["quality_after"] = _graph_quality(session)
    finally:
        driver.close()
    path = MODEL_DIR / f"import_report_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**report, "applied_at": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    if new_entities:
        old = {r.get("entity_id") for r in _read_csv(APPROVED_ENTITIES)}
        _write_csv(APPROVED_ENTITIES, _read_csv(APPROVED_ENTITIES) + [r for r in new_entities.values() if r["entity_id"] not in old])
    print(f"Đã nhập tăng dần; báo cáo: {path}; {report}")
    return report
