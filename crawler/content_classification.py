"""Budgeted, versioned source-text topic and sentiment classification."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests

from .config import INTERIM_DIR, RAW_DIR, VN_TZ

OUTPUT = INTERIM_DIR / "document_classifications.csv"
STATUS = RAW_DIR / "content_classification_status.json"
TOPICS = {"phát hành", "hợp tác", "biểu diễn", "chương trình", "doanh nghiệp", "thương hiệu", "tranh chấp", "khác"}
SENTIMENTS = {"tích cực", "trung tính", "tiêu cực", "hỗn hợp", "chưa xác định"}
FIELDS = ["document_id", "title", "url", "source", "published_at", "content_hash", "model_version", "status", "topics", "sentiment", "quote", "error", "classified_at"]


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _atomic_csv(rows: list[dict]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(OUTPUT)


def _write_status(payload: dict) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    temp = STATUS.with_suffix(".tmp")
    temp.write_text(json.dumps({**payload, "updated_at": datetime.now(VN_TZ).isoformat(timespec="seconds"), "timezone": "Asia/Ho_Chi_Minh"}, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATUS)


def _decode(content: str) -> dict:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("Mô hình phải trả về một JSON object")
    topics = value.get("topics")
    sentiment = value.get("sentiment")
    quote = value.get("quote")
    if not isinstance(topics, list) or any(topic not in TOPICS for topic in topics):
        raise ValueError("Nhãn chủ đề không thuộc bộ nhãn đã quy định")
    if sentiment not in SENTIMENTS:
        raise ValueError("Nhãn sắc thái không thuộc bộ nhãn đã quy định")
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("Thiếu trích dẫn từ nội dung nguồn")
    return {"topics": sorted(set(topics)), "sentiment": sentiment, "quote": quote}


def _input_documents() -> list[dict]:
    paths = [INTERIM_DIR / "web_live_documents.csv", INTERIM_DIR / "live_documents.csv"]
    documents = {}
    for path in paths:
        for row in _read_rows(path):
            document_id = (row.get("document_id") or "").strip()
            content = (row.get("content") or row.get("title") or "").strip()
            if document_id and content:
                documents[document_id] = {"document_id": document_id, "title": row.get("title") or "", "url": row.get("url") or "", "source": row.get("source_name") or "", "published_at": row.get("published_at") or "", "content": content}
    return list(documents.values())


def classify_pending(limit: int | None = None) -> dict:
    """Classify prepared live documents. Missing credentials or model errors never invent labels."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", "").strip() or os.getenv("WEB_RELATION_REVIEW_MODEL", "").strip()
    base_url = (os.getenv("OPENROUTER_BASE_URL", "").strip() or os.getenv("OPENAI_BASE_URL", "").strip() or "https://openrouter.ai/api/v1").rstrip("/")
    documents = _input_documents()
    if not api_key or not model:
        result = {"status": "not_configured", "model_version": model or None, "pending": len(documents), "classified": 0, "failed": 0}
        _write_status(result)
        return result

    records = _read_rows(OUTPUT)
    latest = {}
    for row in records:
        latest[(row.get("document_id"), row.get("content_hash"), row.get("model_version"))] = row
    budget = max(0, limit if limit is not None else int(os.getenv("CONTENT_CLASSIFICATION_DAILY_LIMIT", "25")))
    pending = []
    for doc in documents:
        content_hash = hashlib.sha256(doc["content"].encode("utf-8")).hexdigest()
        key = (doc["document_id"], content_hash, model)
        if latest.get(key, {}).get("status") != "ready":
            pending.append((doc, content_hash, key))
    result = {"status": "running", "model_version": model, "pending": len(pending), "classified": 0, "failed": 0, "budget": budget, "steps": {}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = os.getenv("OPENROUTER_HTTP_REFERER", "http://localhost")
        headers["X-Title"] = os.getenv("OPENROUTER_APP_TITLE", "VN Music Radar")
    for doc, content_hash, key in pending[:budget]:
        text = doc["content"][:14000]
        row = {"document_id": doc["document_id"], "title": doc["title"], "url": doc["url"], "source": doc["source"], "published_at": doc["published_at"], "content_hash": content_hash, "model_version": model, "status": "error", "topics": "", "sentiment": "", "quote": "", "error": "", "classified_at": datetime.now(VN_TZ).isoformat(timespec="seconds")}
        try:
            response = requests.post(f"{base_url}/chat/completions", headers=headers, json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "Phân loại nội dung nguồn bằng tiếng Việt. Chỉ trả JSON với topics (mảng nhiều nhãn có thể rỗng), sentiment và quote. Chủ đề chỉ dùng: phát hành, hợp tác, biểu diễn, chương trình, doanh nghiệp, thương hiệu, tranh chấp, khác. Sắc thái chỉ dùng: tích cực, trung tính, tiêu cực, hỗn hợp, chưa xác định. Sắc thái mô tả nội dung nguồn, không phải cảm xúc công chúng. quote phải là trích đoạn nguyên văn trong văn bản; không suy diễn sự kiện. Nếu không chắc, topics=[] và sentiment=chưa xác định."},
                    {"role": "user", "content": json.dumps({"title": doc["title"], "text": text}, ensure_ascii=False)},
                ],
            }, timeout=float(os.getenv("CONTENT_CLASSIFICATION_TIMEOUT", "45")))
            response.raise_for_status()
            payload = response.json()
            parsed = _decode(payload["choices"][0]["message"]["content"])
            if parsed["quote"] not in text:
                raise ValueError("Trích dẫn của mô hình không có nguyên văn trong đoạn nguồn được gửi")
            row.update({"status": "ready", "topics": "|".join(parsed["topics"]), "sentiment": parsed["sentiment"], "quote": parsed["quote"]})
            result["classified"] += 1
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            result["failed"] += 1
        records.append(row)
        latest[key] = row
        _write_status({**result, "status": "running", "last_document_id": doc["document_id"]})
    result["remaining"] = max(0, len(pending) - budget)
    result["status"] = "ok" if not result["failed"] and result["remaining"] == 0 else ("partial" if result["classified"] or result["failed"] else "budget_limited")
    if not pending:
        result["status"] = "ok"
    _atomic_csv(records)
    _write_status(result)
    return result
