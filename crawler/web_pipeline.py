"""Recover, normalize, review, and export web-only article relations."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.parse
from collections import Counter
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import trafilatura

from . import web
from .config import INTERIM_DIR, PERIOD_END, PERIOD_START, RAW_DIR, ROOT

OUT_DIR = ROOT / "data" / "processed" / "web"
GRAPH_DIR = OUT_DIR / "graph_clean"
RECOVERED = OUT_DIR / "recovered_documents.csv"
RECOVERY_REPORT = OUT_DIR / "recovery_report.json"
MERGE_REPORT = OUT_DIR / "merge_report.json"
ARTICLES = OUT_DIR / "articles.csv"
READY = OUT_DIR / "articles_ready.csv"
REVIEW = OUT_DIR / "articles_review.csv"
EXCLUDED = OUT_DIR / "articles_excluded.csv"
DUPLICATES = OUT_DIR / "duplicate_groups.csv"
QUALITY_REPORT = OUT_DIR / "quality_report.json"
ENTITY_REVIEW = OUT_DIR / "entity_review.csv"
REVIEW_DECISIONS = OUT_DIR / "relation_decisions.csv"
SIGNALS = OUT_DIR / "relation_candidates.csv"
SIGNAL_REPORT = OUT_DIR / "relation_report.json"
GRAPH_REPORT = OUT_DIR / "graph_report.json"

ARTICLE_EXTRA = ["canonical_url", "body_text", "body_source", "extraction_version", "quality_status", "scope_status", "quality_flags", "duplicate_group_id", "duplicate_of", "entity_match_status"]
RELATION_EXTRA = ["reviewed_by", "reviewed_at", "decision_content_hash"]
DECISION_COLUMNS = ["signal_id", "review_status", "decision_reason", "reviewed_by", "reviewed_at", "candidate_content_hash", "decision_content_hash"]
DUP_COLUMNS = ["duplicate_group_id", "document_id", "url", "canonical_url", "content_hash", "representative_document_id", "duplicate_kind"]
ENTITY_REVIEW_COLUMNS = ["document_id", "mention", "candidate_entity_ids", "candidate_names", "match_status", "url", "quote"]


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _atomic_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _value_summary(value) -> dict:
    text = str(value or "")
    return {"length": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "preview": text[:240]}


def _processed_db_rows() -> list[dict]:
    db_path = web.DB_PATH
    if not db_path.exists():
        return []
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute("SELECT * FROM urls WHERE state IN ('crawled','needs_review','out_of_period') ORDER BY url")]
    finally:
        db.close()


def recover(dry_run: bool = False) -> dict:
    """Extract documents for DB-processed URLs absent from the raw CSV."""
    raw_rows = _read_csv(web.DOCS_PATH)
    existing_urls = {r.get("url", "") for r in raw_rows}
    processed = [r for r in _processed_db_rows() if r.get("url") not in existing_urls]
    if dry_run:
        result = {"candidates": len(processed), "dry_run": True, "output": str(RECOVERED)}
        print(json.dumps(result, ensure_ascii=False))
        return result

    sources = web._sources()
    recovered, failures, status_mismatches = [], [], []
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    for record in processed:
        url = record["url"]
        digest = _url_hash(url)
        html_path = web.WEB_DIR / "html" / f"{digest}.html"
        if not html_path.exists():
            failures.append({"url": url, "error": "không tìm thấy HTML", "html_path": str(html_path)})
            continue
        try:
            html = html_path.read_text(encoding="utf-8")
            ids = [x for x in re.split(r"[,|]", record.get("subject_ids", "")) if x]
            final_url = record.get("final_url") or record.get("resolved_url") or url
            # The old queue has empty subject_ids for these recovered records.
            # Metadata extraction does not require scanning the entire entity
            # catalog; relevance is therefore inherited conservatively from
            # the checkpoint classification below.
            parsed = web._extract_article_html(final_url, html, ids, [], {})
            if record.get("state") == "crawled":
                parsed["relevance"] = "liên quan"
            elif record.get("state") == "needs_review":
                parsed["relevance"] = "cần duyệt liên quan"
            else:
                parsed["relevance"] = "liên quan"
            missing = [name for name, value in (("title", parsed["title"]), ("published_at", parsed["published"]), ("article_lead", parsed["article_lead"])) if not value]
            published = parsed["published"]
            day = date.fromisoformat(published) if published else None
            if day and not PERIOD_START <= day <= PERIOD_END:
                state, status = "out_of_period", "loại bỏ"
            elif missing or parsed["conflict"] or parsed["relevance"] != "liên quan":
                state, status = "needs_review", "cần kiểm tra"
            else:
                state, status = "crawled", "hợp lệ"
            doc_id = "DOC_WEB_" + digest[:20]
            content = parsed["content"] or ""
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
            source = web._source_for_url(final_url, sources)
            reasons = [*(f"thiếu {x}" for x in missing), parsed["conflict"]]
            if state == "out_of_period":
                reasons.append("ngoài kỳ")
            if parsed["relevance"] != "liên quan":
                reasons.append("chưa khớp tên thực thể trong tiêu đề/nội dung")
            row = {key: "" for key in web.DOC_COLUMNS}
            row.update({
                "document_id": doc_id, "url": url,
                "resolved_url": record.get("resolved_url", ""), "final_url": final_url,
                "source_name": source.get("source_name") or record.get("source_name", ""),
                "source_type": source.get("source_type", "website chưa xác minh"),
                "title": parsed["title"], "title_source": parsed["title_source"],
                "abstract": parsed["abstract"], "abstract_source": parsed["abstract_source"],
                "rss_abstract": record.get("rss_abstract", ""),
                "article_lead": parsed["article_lead"], "lead_source": parsed["lead_source"],
                "published_at": published, "published_at_iso": parsed["published_iso"],
                "published_at_raw": parsed["raw"], "published_at_source": parsed["date_source"],
                "published_at_conflict": parsed["conflict"],
                "collected_at": record.get("updated_at") or now, "content": content,
                "raw_html_path": str(html_path.relative_to(ROOT)),
                "collection_method": record.get("source_kind") or "web-recovery",
                "document_status": status, "author": parsed["author"],
                "content_hash": content_hash, "crawl_relevance_status": parsed["relevance"],
                "review_reason": "; ".join(filter(None, reasons)),
                "query_entity_ids": ",".join(ids), "seed_ids": ",".join(sorted(set(parsed["matched"]))),
            })
            recovered.append(row)
            if state != record.get("state"):
                status_mismatches.append({"url": url, "db_state": record.get("state"), "recovered_state": state})
        except Exception as exc:
            failures.append({"url": url, "error": str(exc), "html_path": str(html_path)})
    columns = list(dict.fromkeys(web.DOC_COLUMNS + [k for r in raw_rows for k in r if k not in web.DOC_COLUMNS]))
    _atomic_csv(RECOVERED, recovered, columns)
    report = {"candidates": len(processed), "recovered": len(recovered), "failures": failures,
              "status_mismatches": status_mismatches, "statuses": dict(Counter(r["document_status"] for r in recovered)),
              "recovered_at": now, "output": str(RECOVERED)}
    _atomic_json(RECOVERY_REPORT, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"failures", "status_mismatches"}}, ensure_ascii=False, indent=2))
    return report


def merge(dry_run: bool = False) -> dict:
    """Merge raw CSV, legacy JSONL, and recovery rows without losing provenance."""
    current = _read_csv(web.DOCS_PATH)
    recovered = _read_csv(RECOVERED)
    legacy_path = web.WEB_DIR / "documents.jsonl"
    legacy = []
    legacy_errors = 0
    if legacy_path.exists():
        with legacy_path.open(encoding="utf-8") as f:
            for line_number, line in enumerate(f, 1):
                try:
                    row = json.loads(line)
                    if row.get("document_id"):
                        legacy.append(row)
                except json.JSONDecodeError:
                    legacy_errors += 1
    conflicts = []
    # Current CSV wins; historical and recovered values only fill empty fields.
    merged: dict[str, dict] = {}
    source_by_id: dict[str, str] = {}
    for source_name, rows in (("csv", current), ("recovered", recovered), ("legacy", legacy)):
        for row in rows:
            key = row.get("document_id", "") or "URL:" + row.get("url", "")
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(row)
                source_by_id[key] = source_name
                continue
            target = merged[key]
            for field, value in row.items():
                if value in (None, ""):
                    continue
                if target.get(field) in (None, ""):
                    target[field] = value
                elif str(target[field]) != str(value):
                    conflicts.append({"key": key, "field": field, "preferred_source": source_by_id[key], "preferred_value": _value_summary(target[field]), "other_source": source_name, "other_value": _value_summary(value)})
            if source_name == "csv":
                source_by_id[key] = "csv"
    # Collapse distinct IDs that point at exactly the same input URL, preserving the CSV row where possible.
    by_url: dict[str, str] = {}
    result: dict[str, dict] = {}
    url_collisions = []
    for key, row in merged.items():
        url = row.get("url", "")
        if url and url in by_url:
            existing_key = by_url[url]
            winner = result[existing_key]
            for field, value in row.items():
                if winner.get(field) in (None, "") and value not in (None, ""):
                    winner[field] = value
                elif value not in (None, "") and winner.get(field) != value:
                    conflicts.append({"key": existing_key, "field": field, "preferred_source": "existing-url-row", "preferred_value": _value_summary(winner.get(field, "")), "other_source": source_by_id.get(key, "unknown"), "other_value": _value_summary(value)})
            url_collisions.append({"url": url, "kept_document_id": winner.get("document_id", ""), "merged_document_id": row.get("document_id", "")})
        else:
            result[key] = row
            if url:
                by_url[url] = key
    rows = sorted(result.values(), key=lambda r: (r.get("url", ""), r.get("document_id", "")))
    report = {"csv_rows": len(current), "legacy_rows": len(legacy), "legacy_parse_errors": legacy_errors,
              "recovery_rows": len(recovered), "merged_rows": len(rows),
              "unique_urls": len({r.get("url") for r in rows if r.get("url")}),
              "unique_document_ids": len({r.get("document_id") for r in rows if r.get("document_id")}),
              "conflicts": conflicts, "url_collisions": url_collisions, "dry_run": dry_run}
    if not dry_run:
        columns = list(dict.fromkeys(web.DOC_COLUMNS + [k for r in rows for k in r if k not in web.DOC_COLUMNS]))
        _atomic_csv(web.DOCS_PATH, rows, columns)
        _atomic_json(MERGE_REPORT, report)
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}, ensure_ascii=False, indent=2))
    return report


def _normalize_rows() -> tuple[list[dict], list[dict], list[dict], list[dict], dict]:
    raw = _read_csv(web.DOCS_PATH)
    entities = {e["entity_id"]: e for e in web._entities() if e.get("entity_id")}
    terms = web._relevance_terms(list(entities.values()))
    matcher_by_id: dict[str, list] = {}
    for term in terms:
        matcher_by_id.setdefault(term[0], []).append(term)
    articles, ready, review, excluded, duplicates = [], [], [], [], []
    content_owner: dict[str, str] = {}
    canonical_owner: dict[str, str] = {}
    duplicate_group_by_rep: dict[str, str] = {}
    duplicate_representatives: set[str] = set()
    links = []
    for row in raw:
        doc = {**{key: "" for key in web.DOC_COLUMNS}, **row}
        for field in ("title", "abstract", "article_lead", "content"):
            doc[field] = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", str(doc.get(field) or "").replace("\r", "\n")).strip())
        html_path = ROOT / str(doc.get("raw_html_path", "")) if doc.get("raw_html_path") else None
        body, body_source = doc["content"], "raw:content"
        if html_path and html_path.is_file():
            try:
                html = html_path.read_text(encoding="utf-8", errors="replace")
                body = trafilatura.extract(html, include_comments=False, include_tables=False, output_format="txt") or ""
                if body:
                    body_source = "trafilatura:fulltext"
            except (OSError, ValueError):
                pass
        body = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", body.replace("\r", "\n"))).strip()
        if not body:
            body = doc["article_lead"] or doc["abstract"]
            body_source = "fallback:lead-or-abstract"
        doc["body_text"] = body
        doc["body_source"] = body_source
        doc["extraction_version"] = "web-pipeline-v1"
        doc["title"] = doc["title"].strip()
        published = web._date(doc.get("published_at") or doc.get("published_at_raw", ""))
        doc["published_at"] = published
        final_url = doc.get("final_url") or doc.get("resolved_url") or doc.get("url", "")
        doc["canonical_url"] = ""
        if html_path and html_path.is_file():
            try:
                doc["canonical_url"] = _canonical_from_html(html_path.read_text(encoding="utf-8", errors="replace"), final_url)
            except (OSError, ValueError):
                pass
        doc["content_hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
        raw_ids = doc.get("query_entity_ids") or doc.get("seed_ids") or ""
        known = {x for x in re.split(r"[,|]", raw_ids) if x}
        # Entity matching is performed with relation extraction. Here we only
        # link queue-known entities; scanning the full catalog per article is
        # expensive and is not a document-quality criterion.
        candidate_terms = [t for eid in known for t in matcher_by_id.get(eid, ())]
        text = "\n".join((doc["title"], doc["abstract"], doc["article_lead"], body))
        matched = web._relevance_matches(doc["title"], text, candidate_terms) if candidate_terms else []
        doc["entity_match_status"] = "matched_from_queue" if matched else "queue_entity_not_matched_in_text" if known else "unresolved_for_relation_review"
        why = []
        try:
            parsed_url = urllib.parse.urlparse(doc.get("url", ""))
            valid_url = parsed_url.scheme in {"http", "https"} and bool(parsed_url.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            why.append("invalid_url")
        if not doc["title"]:
            why.append("missing_title")
        if len(body) < 120:
            why.append("short_or_missing_body")
        if not published or not doc.get("published_at_source") or str(doc.get("published_at_source", "")).startswith("Google News RSS"):
            why.append("unverified_published_date")
        if doc.get("published_at_conflict"):
            why.append("published_date_conflict")
        if not doc.get("final_url") and not doc.get("resolved_url"):
            why.append("unverified_article_url")
        day = date.fromisoformat(published) if published else None
        scope = "unknown" if day is None else "in_period" if PERIOD_START <= day <= PERIOD_END else "out_of_period"
        doc["scope_status"] = scope
        doc["quality_flags"] = "|".join(why)
        doc["quality_status"] = "ready" if not why and scope == "in_period" else "review" if scope != "out_of_period" else "excluded"
        canonical_key = doc["canonical_url"] or doc.get("final_url") or doc.get("resolved_url")
        kind = ""
        previous = None
        if canonical_key and canonical_key in canonical_owner:
            kind, previous = "canonical_or_final_url", canonical_owner[canonical_key]
        elif doc["content_hash"] and doc["content_hash"] in content_owner:
            kind, previous = "identical_content", content_owner[doc["content_hash"]]
        group_id = ""
        if previous:
            group_id = duplicate_group_by_rep.setdefault(previous, "DUP_WEB_" + hashlib.sha256(previous.encode()).hexdigest()[:16])
            doc["duplicate_group_id"], doc["duplicate_of"] = group_id, previous
            duplicates.append({"duplicate_group_id": group_id, "document_id": doc["document_id"], "url": doc["url"], "canonical_url": doc["canonical_url"], "content_hash": doc["content_hash"], "representative_document_id": previous, "duplicate_kind": kind})
            if previous not in duplicate_representatives:
                representative = next((item for item in articles if item.get("document_id") == previous), None)
                if representative is not None:
                    representative["duplicate_group_id"] = group_id
                    duplicates.append({"duplicate_group_id": group_id, "document_id": previous, "url": representative.get("url", ""), "canonical_url": representative.get("canonical_url", ""), "content_hash": representative.get("content_hash", ""), "representative_document_id": previous, "duplicate_kind": "representative"})
                    duplicate_representatives.add(previous)
        else:
            doc["duplicate_group_id"], doc["duplicate_of"] = "", ""
            if canonical_key:
                canonical_owner[canonical_key] = doc["document_id"]
            if doc["content_hash"]:
                content_owner[doc["content_hash"]] = doc["document_id"]
        articles.append(doc)
        (ready if doc["quality_status"] == "ready" else excluded if doc["quality_status"] == "excluded" else review).append(doc)
        for eid in matched:
            links.append({"document_id": doc["document_id"], "entity_id": eid, "entity_name": entities.get(eid, {}).get("canonical_name", ""), "match_method": "title-or-body"})
    return articles, ready, review, excluded, {"duplicates": duplicates, "links": links}


def normalize() -> dict:
    articles, ready, review, excluded, extra = _normalize_rows()
    columns = list(dict.fromkeys(web.DOC_COLUMNS + ARTICLE_EXTRA))
    for path, rows in ((ARTICLES, articles), (READY, ready), (REVIEW, review), (EXCLUDED, excluded)):
        _atomic_csv(path, rows, columns)
    _atomic_csv(DUPLICATES, extra["duplicates"], DUP_COLUMNS)
    link_path = OUT_DIR / "document_entities.csv"
    _atomic_csv(link_path, extra["links"], ["document_id", "entity_id", "entity_name", "match_method"])
    linked_ids = {r["document_id"] for r in extra["links"]}
    entity_review = [{"document_id": r["document_id"], "mention": "", "candidate_entity_ids": "", "candidate_names": "", "match_status": "chưa nối được ID từ URL crawl hoặc từ điển hiện có", "url": r.get("url", ""), "quote": r.get("title", "")}
                     for r in articles if r.get("document_id") not in linked_ids and r.get("quality_status") != "excluded"]
    _atomic_csv(ENTITY_REVIEW, entity_review, ENTITY_REVIEW_COLUMNS)
    report = {"raw_documents": len(_read_csv(web.DOCS_PATH)), "normalized": len(articles), "ready": len(ready), "review": len(review), "excluded": len(excluded), "duplicate_rows": sum(1 for r in extra["duplicates"] if r["duplicate_kind"] != "representative"), "duplicate_groups": len({r["representative_document_id"] for r in extra["duplicates"]}), "entity_links": len(extra["links"]), "documents_for_entity_review": len(entity_review), "scope": [PERIOD_START.isoformat(), PERIOD_END.isoformat()]}
    _atomic_json(QUALITY_REPORT, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _entity_catalog() -> dict[str, dict]:
    path = INTERIM_DIR / "graph" / "entities.csv"
    rows = _read_csv(path)
    return {r["entity_id"]: r for r in rows if r.get("entity_id")}


def _canonical_from_html(html: str, base_url: str) -> str:
    class CanonicalParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.href = ""

        def handle_starttag(self, tag, attrs):
            if tag.lower() != "link":
                return
            values = {key.lower(): value or "" for key, value in attrs}
            rel = {value.lower() for value in values.get("rel", "").split()}
            if "canonical" in rel and values.get("href"):
                self.href = values["href"]

    parser = CanonicalParser()
    parser.feed(html)
    candidate = urllib.parse.urljoin(base_url, parser.href) if parser.href else ""
    try:
        parsed = urllib.parse.urlparse(candidate)
        return candidate if parsed.scheme in {"http", "https"} and parsed.hostname else ""
    except ValueError:
        return ""


def build_signals() -> dict:
    """Run existing rule-based signal extraction over normalized web articles."""
    from . import web_signals

    catalog = _entity_catalog()
    docs = _read_csv(READY)
    old_rows = _read_csv(SIGNALS)
    ws = web_signals
    # The legacy detector intentionally reads only web rows; provide normalized body text.
    signal_docs = []
    for doc in docs:
        if doc.get("duplicate_of"):
            continue
        signal_docs.append({**doc, "content": doc.get("body_text") or doc.get("content", "")})
    # Call the detector after temporarily redirecting its document source through web._read_docs.
    original_read = web._read_docs
    web._read_docs = lambda: signal_docs
    try:
        frame = ws.build(write=False)
    finally:
        web._read_docs = original_read
    fresh = frame.to_dict("records")
    by_id = {r.get("signal_id"): r for r in old_rows if r.get("signal_id")}
    decisions = {r.get("signal_id"): r for r in _read_csv(REVIEW_DECISIONS) if r.get("signal_id")}
    for row in fresh:
        prior = decisions.get(row.get("signal_id")) or by_id.get(row.get("signal_id"))
        if prior:
            prior_hash = prior.get("decision_content_hash") or prior.get("candidate_content_hash") or prior.get("reviewed_content_hash") or prior.get("document_content_hash", "")
            decided = prior.get("review_status") in {"accepted", "rejected", "unverified"}
            if decided and prior_hash != row.get("document_content_hash", ""):
                row["review_status"] = "stale"
                row["query_status"] = "nội dung đã đổi"
                row["review_note"] = "Nội dung tài liệu thay đổi kể từ lần duyệt"
            else:
                for key in ("review_status", "review_note", "reviewed_by", "reviewed_at", "decision_content_hash"):
                    if prior.get(key):
                        row[key] = prior[key]
                if decided:
                    row["decision_content_hash"] = prior_hash
        row.setdefault("reviewed_by", "")
        row.setdefault("reviewed_at", "")
        row.setdefault("decision_content_hash", "")
        row["candidate_content_hash"] = row.get("document_content_hash", "")
        if row.get("review_status") not in {"accepted", "rejected", "unverified", "stale"}:
            row["review_status"] = "unreviewed"
        row.setdefault("decision_reason", "")
        entity_a = catalog.get(row.get("entity_a_id", ""), {})
        entity_b = catalog.get(row.get("entity_b_id", ""), {})
        row["entity_a_type"] = entity_a.get("entity_type", "")
        row["entity_b_type"] = entity_b.get("entity_type", "")
    cols = list(dict.fromkeys(list(frame.columns) + RELATION_EXTRA + ["candidate_content_hash", "decision_reason", "entity_a_type", "entity_b_type"]))
    _atomic_csv(SIGNALS, fresh, cols)
    # Keep the editable decision ledger in sync without discarding old decisions.
    current = {r.get("signal_id"): r for r in _read_csv(REVIEW_DECISIONS)
               if r.get("signal_id") and r.get("review_status") in {"accepted", "rejected", "unverified", "stale"}}
    for row in fresh:
        current.setdefault(row["signal_id"], {"signal_id": row["signal_id"], "review_status": row["review_status"], "decision_reason": row.get("decision_reason", ""), "reviewed_by": row.get("reviewed_by", ""), "reviewed_at": row.get("reviewed_at", ""), "candidate_content_hash": row.get("candidate_content_hash", ""), "decision_content_hash": row.get("decision_content_hash", "")})
    ledger_columns = DECISION_COLUMNS
    _atomic_csv(REVIEW_DECISIONS, list(current.values()), ledger_columns)
    report = {"normalized_articles": len(docs), "signals": len(fresh), "statuses": dict(Counter(r.get("review_status", "") for r in fresh)), "entity_catalog_size": len(catalog), "candidate_output": str(SIGNALS), "decision_ledger": str(REVIEW_DECISIONS)}
    _atomic_json(SIGNAL_REPORT, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def set_decision(signal_id: str, decision: str, reason: str = "", reviewer: str = "") -> None:
    allowed = {"accepted", "rejected", "unverified"}
    if decision not in allowed:
        raise ValueError(f"decision phải là một trong {sorted(allowed)}")
    if not reviewer.strip():
        raise ValueError("Cần ghi --reviewer để lưu dấu vết người duyệt")
    if decision == "accepted" and not reason.strip():
        raise ValueError("Quyết định accepted cần --reason nêu căn cứ trong bài")
    candidates = _read_csv(SIGNALS)
    row = next((r for r in candidates if r.get("signal_id") == signal_id), None)
    if row is None:
        raise ValueError(f"Không tìm thấy signal_id: {signal_id}")
    row["review_status"] = decision
    row["decision_reason"] = reason
    row["reviewed_by"] = reviewer
    row["reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    row["decision_content_hash"] = row.get("document_content_hash", "")
    _atomic_csv(SIGNALS, candidates, list(dict.fromkeys(k for r in candidates for k in r)))
    ledger = {r.get("signal_id"): r for r in _read_csv(REVIEW_DECISIONS) if r.get("signal_id")}
    ledger[signal_id] = {"signal_id": signal_id, "review_status": decision, "decision_reason": reason, "reviewed_by": reviewer, "reviewed_at": row["reviewed_at"], "candidate_content_hash": row.get("document_content_hash", ""), "decision_content_hash": row["decision_content_hash"]}
    _atomic_csv(REVIEW_DECISIONS, list(ledger.values()), DECISION_COLUMNS)


def apply_decisions() -> dict:
    """Apply spreadsheet-edited decisions after checking reviewer and content hash."""
    ledger = _read_csv(REVIEW_DECISIONS)
    candidates = _read_csv(SIGNALS)
    candidate_by_id = {r.get("signal_id"): r for r in candidates}
    applied = 0
    errors = []
    for row in ledger:
        decision = row.get("review_status", "")
        if decision not in {"accepted", "rejected", "unverified"}:
            continue
        signal = candidate_by_id.get(row.get("signal_id"))
        if not signal:
            errors.append({"signal_id": row.get("signal_id", ""), "error": "candidate_not_found"})
            continue
        content_hash = row.get("candidate_content_hash", "")
        if (not row.get("reviewed_by", "").strip() or not content_hash
                or content_hash != signal.get("document_content_hash")
                or (decision == "accepted" and not row.get("decision_reason", "").strip())):
            errors.append({"signal_id": row.get("signal_id", ""), "error": "reviewer_or_current_content_hash_missing_or_mismatched"})
            continue
        signal["review_status"] = decision
        signal["decision_reason"] = row.get("decision_reason", "")
        signal["reviewed_by"] = row["reviewed_by"]
        signal["reviewed_at"] = row.get("reviewed_at", "") or datetime.now().astimezone().isoformat(timespec="seconds")
        signal["decision_content_hash"] = content_hash
        row["reviewed_at"] = signal["reviewed_at"]
        row["decision_content_hash"] = content_hash
        applied += 1
    if errors:
        raise ValueError(f"Không áp dụng {len(errors)} quyết định; xem ví dụ: {errors[:5]}")
    _atomic_csv(SIGNALS, candidates, list(dict.fromkeys(k for r in candidates for k in r)))
    _atomic_csv(REVIEW_DECISIONS, ledger, DECISION_COLUMNS)
    result = {"applied_decisions": applied, "candidate_signals": len(candidates), "output": str(SIGNALS)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def build_graph() -> dict:
    """Export a web-only graph from accepted evidence; never touches the main graph."""
    from .graph import ENTITY_COLUMNS, RELATION_COLUMNS, EVIDENCE_COLUMNS

    docs = {r.get("document_id"): r for r in _read_csv(READY) if r.get("document_id")}
    entities = _entity_catalog()
    signals = _read_csv(SIGNALS)
    accepted = []
    rejected = []
    for row in signals:
        if row.get("review_status") != "accepted":
            continue
        doc = docs.get(row.get("document_id"))
        quote = row.get("quote", "")
        full_text = "\n".join((doc.get("title", ""), doc.get("abstract", ""), doc.get("article_lead", ""), doc.get("body_text", ""))) if doc else ""
        if (not doc or not quote or row.get("url") != doc.get("url", "") or quote not in full_text
                or row.get("document_content_hash") != doc.get("content_hash")
                or row.get("decision_content_hash") != doc.get("content_hash")):
            rejected.append({"signal_id": row.get("signal_id"), "reason": "missing_document_or_quote_or_hash_mismatch"})
            continue
        if row.get("entity_a_id") not in entities or row.get("entity_b_id") not in entities:
            rejected.append({"signal_id": row.get("signal_id"), "reason": "unknown_entity_endpoint"})
            continue
        accepted.append((row, doc))
    out_entities, relations, evidence = {}, {}, {}
    entity_docs: dict[str, set[str]] = {}
    entity_relations: dict[str, set[str]] = {}
    relation_docs: dict[str, set[str]] = {}
    for row, doc in accepted:
        for eid in (row["entity_a_id"], row["entity_b_id"]):
            src = entities[eid]
            out_entities[eid] = {key: src.get(key, "") for key in ENTITY_COLUMNS}
            entity_docs.setdefault(eid, set()).add(doc["document_id"])
        key = (row["entity_a_id"], row["relation_type"], row["entity_b_id"])
        rid = "REL_WEB_" + hashlib.sha256("\0".join(key).encode()).hexdigest()[:20]
        if rid not in relations:
            relations[rid] = {"relation_id": rid, "source_entity_id": key[0], "relation_type": key[1], "target_entity_id": key[2], "verification_status": "đã xác minh", "is_derived": "không", "valid_from": row.get("event_date", ""), "valid_to": "", "role_detail": row.get("role_detail", ""), "notes": "web evidence reviewed", "source_name": out_entities[key[0]].get("canonical_name", ""), "target_name": out_entities[key[2]].get("canonical_name", ""), "n_documents": ""}
        entity_relations.setdefault(key[0], set()).add(rid)
        entity_relations.setdefault(key[2], set()).add(rid)
        relation_docs.setdefault(rid, set()).add(doc["document_id"])
        ev_id = "EVD_WEB_" + hashlib.sha256("\0".join((rid, row["signal_id"])).encode()).hexdigest()[:20]
        evidence[ev_id] = {"evidence_id": ev_id, "relation_id": rid, "document_id": row["document_id"], "quote": row["quote"], "sentence_location": row.get("sentence_location", ""), "extraction_method": row.get("extraction_method", ""), "review_status": "đã xác minh", "review_note": row.get("decision_reason", ""), "confidence_score": "", "url": row["url"]}
    for eid, entity in out_entities.items():
        entity["n_documents"] = len(entity_docs.get(eid, ()))
        entity["n_relations"] = len(entity_relations.get(eid, ()))
    for rid, relation in relations.items():
        relation["n_documents"] = len(relation_docs.get(rid, ()))
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_csv(GRAPH_DIR / "entities.csv", list(out_entities.values()), ENTITY_COLUMNS)
    _atomic_csv(GRAPH_DIR / "relations.csv", list(relations.values()), RELATION_COLUMNS)
    _atomic_csv(GRAPH_DIR / "evidence.csv", list(evidence.values()), EVIDENCE_COLUMNS)
    graph_docs = list({doc["document_id"]: doc for _, doc in accepted}.values())
    doc_cols = list(dict.fromkeys(web.DOC_COLUMNS + ARTICLE_EXTRA))
    _atomic_csv(GRAPH_DIR / "documents.csv", graph_docs, doc_cols)
    report = {"web_documents_ready": len(docs), "candidate_signals": len(signals), "accepted_signals": len(accepted), "relations": len(relations), "evidence": len(evidence), "entities": len(out_entities), "excluded_accepted_signals": rejected}
    _atomic_json(GRAPH_REPORT, report)
    print(json.dumps({k: v for k, v in report.items() if k != "excluded_accepted_signals"} | {"excluded_accepted_signals": len(rejected)}, ensure_ascii=False, indent=2))
    return report


def pipeline(dry_run: bool = False) -> dict:
    recovery = recover(dry_run=dry_run)
    if dry_run:
        return {"recovery": recovery}
    merge_report = merge(dry_run=False)
    quality = normalize()
    relations = build_signals()
    graph = build_graph()
    return {"recovery": recovery, "merge": merge_report, "quality": quality, "relations": relations, "graph": graph}
