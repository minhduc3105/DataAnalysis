"""Versioned exchange contract for the extraction and language-model service."""

from __future__ import annotations

import json
import math
from numbers import Real
import os
import time
from pathlib import Path
from typing import Any

import requests

SCHEMA_VERSION = "vn-music-radar.v1"
ENTITY_TYPES = {"Person", "Group", "Song", "Album", "Company", "Show", "Event", "Brand"}
RELATION_SIGNATURES = {
    "PERFORMED": ({"Person", "Group"}, {"Song"}),
    "FEATURED_ON": ({"Person", "Group"}, {"Song"}),
    "COMPOSED": ({"Person"}, {"Song"}),
    "PRODUCED": ({"Person"}, {"Song"}),
    "RELEASED_BY": ({"Song", "Album"}, {"Company"}),
    "TRACK_OF": ({"Song"}, {"Album"}),
    "MEMBER_OF": ({"Person"}, {"Group"}),
    "CONTESTANT_ON": ({"Person"}, {"Show"}),
    "JUDGE_ON": ({"Person"}, {"Show"}),
    "PERFORMED_AT": ({"Person", "Group"}, {"Show", "Event"}),
    "ORGANIZED_BY": ({"Show", "Event"}, {"Company"}),
    "AMBASSADOR_OF": ({"Person", "Group"}, {"Brand"}),
    "COLLABORATED_WITH": ({"Person", "Group"}, {"Person", "Group"}),
    "DISPUTED_WITH": ({"Person", "Company"}, {"Person", "Company"}),
}
UNDIRECTED = {"COLLABORATED_WITH", "DISPUTED_WITH"}


class ModelServiceError(RuntimeError):
    pass


def validate_extraction(row: dict[str, Any], documents: dict[str, str]) -> list[str]:
    """Return all contract and evidence errors for one extraction record."""
    errors: list[str] = []
    document_id = str(row.get("document_id", ""))
    if "is_fixture" in row and not isinstance(row["is_fixture"], bool):
        errors.append("is_fixture phải là boolean")
    if row.get("is_fixture") and not str(row.get("fixture_text", "")).strip():
        errors.append("fixture phải có fixture_text để kiểm tra mention và bằng chứng")
    content = documents.get(document_id)
    if not document_id or content is None:
        errors.append("document_id không tồn tại trong tập tài liệu")
        content = ""
    if row.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version phải là {SCHEMA_VERSION}")
    if not str(row.get("model_version", "")).strip():
        errors.append("thiếu model_version")
    entities = row.get("entities")
    relations = row.get("relations")
    if not isinstance(entities, list) or not isinstance(relations, list):
        return errors + ["entities và relations phải là danh sách"]

    by_id: dict[str, dict[str, Any]] = {}
    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            errors.append(f"entities[{i}] phải là object")
            continue
        mid, text, etype = str(entity.get("mention_id", "")), str(entity.get("text", "")), entity.get("type")
        if not mid or mid in by_id:
            errors.append(f"entities[{i}].mention_id thiếu hoặc trùng")
        if not text or etype not in ENTITY_TYPES:
            errors.append(f"entities[{i}] có text rỗng hoặc type không hợp lệ")
        elif text.casefold() not in content.casefold():
            errors.append(f"mention {mid or i} không xuất hiện trong văn bản")
        if mid:
            by_id[mid] = entity

    for i, relation in enumerate(relations):
        if not isinstance(relation, dict):
            errors.append(f"relations[{i}] phải là object")
            continue
        head = by_id.get(str(relation.get("head_mention_id", "")))
        tail = by_id.get(str(relation.get("tail_mention_id", "")))
        rtype = relation.get("type")
        evidence = str(relation.get("evidence", "")).strip()
        confidence = relation.get("confidence")
        if not head or not tail:
            errors.append(f"relations[{i}] tham chiếu mention không tồn tại")
            continue
        signature = RELATION_SIGNATURES.get(str(rtype))
        if not signature:
            errors.append(f"relations[{i}] có relation type không hợp lệ")
        elif head.get("type") not in signature[0] or tail.get("type") not in signature[1]:
            if rtype not in UNDIRECTED or tail.get("type") not in signature[0] or head.get("type") not in signature[1]:
                errors.append(f"relations[{i}] sai hướng hoặc kiểu thực thể cho {rtype}")
        if not evidence or evidence.casefold() not in content.casefold():
            errors.append(f"relations[{i}] câu bằng chứng không có trong văn bản")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            errors.append(f"relations[{i}].confidence phải nằm trong [0, 1]")
    return errors


class ModelClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120, retries: int = 2):
        self.base_url = (base_url or os.getenv("MODEL_API_BASE_URL", "http://127.0.0.1:8001")).rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(f"{self.base_url}/{endpoint.lstrip('/')}", json=payload, timeout=self.timeout)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ModelServiceError(f"/{endpoint} phải trả JSON object")
                return result
            except (requests.RequestException, ValueError, ModelServiceError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 4))
        raise ModelServiceError(f"Không gọi được {self.base_url}/{endpoint}: {last_error}") from last_error

    def embed(self, texts: list[str]) -> tuple[str, int, list[list[float]]]:
        result = self.post("embed", {"schema_version": SCHEMA_VERSION, "texts": texts})
        model = str(result.get("model_version", ""))
        vectors = result.get("vectors")
        if not model or not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ModelServiceError("/embed phải trả model_version và một vector cho mỗi văn bản")
        dimensions = int(result.get("dimensions") or (len(vectors[0]) if vectors else 0))
        if dimensions < 1 or any(not isinstance(v, list) or len(v) != dimensions for v in vectors):
            raise ModelServiceError("Số chiều vector thiếu hoặc không đồng nhất")
        if any(not isinstance(x, Real) or isinstance(x, bool) or not math.isfinite(float(x)) for vector in vectors for x in vector):
            raise ModelServiceError("/embed phải trả vector chỉ gồm số hữu hạn")
        return model, dimensions, [[float(x) for x in vector] for vector in vectors]


def load_contract() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "schemas" / "model_contract_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))
