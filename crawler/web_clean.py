"""Normalize, de-duplicate, and period-filter downloaded web documents."""

import json
import re
import urllib.parse
import unicodedata

import pandas as pd

from . import web
from .common import normalize_name
from .config import INTERIM_DIR, PERIOD_END, PERIOD_START

OUT_PATH = INTERIM_DIR / "web_documents.csv"
LINK_PATH = INTERIM_DIR / "document_entities.csv"
REVIEW_PATH = INTERIM_DIR / "web_review.csv"
REJECTED_PATH = INTERIM_DIR / "web_rejected.csv"
REPORT_PATH = INTERIM_DIR / "web_quality_report.json"


def _clean_text(value):
    value = unicodedata.normalize("NFC", str(value or ""))
    value = value.replace("\r", "\n").replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def clean():
    docs = pd.DataFrame(web._read_docs()).fillna("")
    if docs.empty:
        for path, columns in ((OUT_PATH, web.DOC_COLUMNS), (REVIEW_PATH, web.DOC_COLUMNS), (REJECTED_PATH, web.DOC_COLUMNS), (LINK_PATH, ["document_id", "entity_id", "entity_name", "match_method"])):
            pd.DataFrame(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")
        INTERIM_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps({"total_raw": 0, "clean": 0, "review": 0, "rejected": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Chưa có tài liệu web thô.")
        return

    entities = web._entities()
    matcher = web._relevance_terms(entities)
    matcher_by_id = {}
    for term in matcher:
        matcher_by_id.setdefault(term[0], []).append(term)
    entity_by_id = {e["entity_id"]: e for e in entities}
    for col in web.DOC_COLUMNS:
        if col not in docs:
            docs[col] = ""
    docs["title"] = docs["title"].map(_clean_text)
    docs["abstract"] = docs["abstract"].map(_clean_text)
    docs["content"] = docs.apply(lambda row: _clean_text(row.get("content") or row.get("abstract")), axis=1)
    docs["published_at"] = docs.apply(lambda r: r.get("published_at", "") or web._date(r.get("published_at_raw", "")), axis=1)
    docs["published_at_iso"] = docs.apply(lambda r: r.get("published_at_iso", "") or web._published_iso(r.get("published_at_raw", "")), axis=1)
    # Keep a separate document for every exact source URL. Equal content is a
    # review hint, never a reason to discard a distinct source link.

    accepted, reviews, rejected, links = [], [], [], []
    reason_counts = {}
    by_year = {}
    by_source = {}
    for row in docs.to_dict("records"):
        url, content, title = row.get("url", ""), row.get("content", ""), row.get("title", "")
        published = web._date(row.get("published_at", ""))
        raw_path = row.get("raw_html_path", "")
        source_present = bool(row.get("published_at_source")) and not str(row.get("published_at_source", "")).startswith("Google News RSS")
        conflict = row.get("published_at_conflict", "")
        in_period = bool(published and PERIOD_START.isoformat() <= published <= PERIOD_END.isoformat())
        should_verify_html = not published or (in_period and (not source_present or bool(conflict)))
        if should_verify_html and raw_path:
            try:
                with (web.ROOT / raw_path).open("rb") as html_file:
                    raw_html = html_file.read(100_000).decode("utf-8", errors="replace")
                raw, source, published, conflict = web._page_publication_dates(raw_html)
                row.update(published_at=published, published_at_raw=raw, published_at_source=source, published_at_conflict=conflict)
                row["published_at_iso"] = web._published_iso(raw)
                source_present = bool(source)
            except OSError:
                pass
        raw_ids = row.get("query_entity_ids", "") or row.get("seed_ids", "") or row.get("entity_ids", "")
        known = set(x for x in re.split(r"[,|]", raw_ids) if x)
        # Prior extraction already recorded candidate IDs; restrict matching to them.
        # New RSS documents without attached IDs still search the full graph.
        candidate_matcher = [term for eid in known for term in matcher_by_id.get(eid, ())] if known else matcher
        matches = web._relevance_matches(title, title + "\n" + row.get("abstract", "") + "\n" + content, candidate_matcher)
        for eid in matches:
            entity = entity_by_id.get(eid, {})
            links.append({"document_id": row.get("document_id", ""), "entity_id": eid, "entity_name": entity.get("canonical_name", ""), "match_method": "tiêu đề/nội dung"})

        why = []
        try:
            parsed = urllib.parse.urlparse(url)
            valid_http = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        except ValueError:
            valid_http = False
        if not valid_http:
            why.append("URL không phải HTTP/HTTPS hợp lệ")
        elif not web._is_article_url(row.get("final_url") or url):
            why.append("đích tải không có dạng bài viết thông thường")
        if row.get("collection_method") == "google_news_preview" or (row.get("final_url") and (urllib.parse.urlparse(row.get("final_url", "")).hostname or "").lower() == "news.google.com"):
            why.append("bản ghi preview Google News cũ chưa xác minh từ bài báo gốc")
        if len(content) < 120:
            why.append("chưa đủ nội dung bài viết")
        if not title or not row.get("title_source"):
            why.append("thiếu tiêu đề bài gốc đã xác minh")
        if not row.get("article_lead") or not row.get("lead_source"):
            why.append("thiếu đoạn mở đầu bài gốc đã xác minh")
        if not published or not source_present:
            why.append("thiếu ngày đăng xác minh từ bài gốc")
        elif conflict:
            why.append("metadata ngày đăng mâu thuẫn")
        elif not (PERIOD_START.isoformat() <= published <= PERIOD_END.isoformat()):
            why.append("ngoài phạm vi thời gian")
        if not matches:
            why.append("không tìm thấy tên thực thể trong tiêu đề/nội dung; kiểm tra kết quả truy vấn")
        row["published_at"] = published
        row["review_reason"] = "|".join(why)
        for reason in why:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if why and "ngoài phạm vi thời gian" in why:
            row["document_status"] = "loại bỏ"
            row["exclude_reason"] = "|".join(why)
            rejected.append(row)
        elif why:
            row["document_status"] = "cần kiểm tra"
            row["exclude_reason"] = "|".join(why)
            reviews.append(row)
        else:
            row["document_status"] = "hợp lệ"
            row["exclude_reason"] = ""
            accepted.append(row)
            year = published[:4]
            by_year[year] = by_year.get(year, 0) + 1
            by_source[row.get("source_name", "")] = by_source.get(row.get("source_name", ""), 0) + 1

    for path, rows in ((OUT_PATH, accepted), (REVIEW_PATH, reviews), (REJECTED_PATH, rejected)):
        frame = pd.DataFrame(rows)
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    pd.DataFrame(links, columns=["document_id", "entity_id", "entity_name", "match_method"]).drop_duplicates().to_csv(LINK_PATH, index=False, encoding="utf-8-sig")
    report = {"total_raw": len(web._read_docs()), "raw_documents": len(docs), "clean": len(accepted), "review": len(reviews), "rejected": len(rejected), "clean_by_year": dict(sorted(by_year.items())), "clean_by_source": by_source, "rejected_by_reason": reason_counts, "period": [PERIOD_START.isoformat(), PERIOD_END.isoformat()]}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Làm sạch xong: {len(accepted)} hợp lệ, {len(reviews)} chờ duyệt, {len(rejected)} loại; xem web_quality_report.json")
