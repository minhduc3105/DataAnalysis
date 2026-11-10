"""Detect reviewable pair-relation signals in collected web documents."""

import hashlib
import json
import re
import unicodedata

import pandas as pd

from . import web
from .common import normalize_name
from .config import INTERIM_DIR, PERIOD_END, PERIOD_START, RAW_DIR, ROOT

TERMS_PATH = ROOT / "seeds" / "web_relation_terms.csv"
OUT_PATH = INTERIM_DIR / "web_relation_candidates.csv"
WEB_DIR = RAW_DIR / "web"
SIGNAL_COLUMNS = ["signal_id", "document_id", "entity_a_id", "entity_a_name", "entity_b_id", "entity_b_name", "relation_type", "relation_already_in_graph", "title", "url", "source_name", "published_at", "event_date", "quote", "sentence_location", "review_status", "query_status", "review_note", "document_content_hash", "reviewed_content_hash", "role_detail", "extraction_method"]


def _key(value):
    return " ".join(normalize_name(unicodedata.normalize("NFC", str(value or ""))).split())


def _accent_key(value):
    value = unicodedata.normalize("NFC", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", value, flags=re.UNICODE))


def _has_phrase(text, phrase):
    text_key, phrase_key = _accent_key(text), _accent_key(phrase)
    return bool(phrase_key and re.search(rf"(?<!\w){re.escape(phrase_key)}(?!\w)", text_key, flags=re.UNICODE))


def _exact_entity_matches(sentence, candidates, exact_names, name_owners):
    matched = set()
    for entity_id in candidates:
        for name, name_key in exact_names.get(entity_id, set()):
            if not name_key or len(name_owners.get(name_key, ())) != 1:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", flags=re.IGNORECASE | re.UNICODE)
            for match in pattern.finditer(unicodedata.normalize("NFC", sentence)):
                value = match.group(0)
                # Reject lower-case mentions embedded in titles such as "Tổ quốc anh về".
                # Proper-name tokens should be capitalized in the article sentence.
                if len(name_key.split()) > 1 and not all(token[:1].isupper() for token in value.split() if token):
                    continue
                if len(name_key.split()) == 1 and value[:1].islower() and not name.islower():
                    continue
                matched.add(entity_id)
                break
    return sorted(matched)


def _stable_id(*parts):
    value = "|".join(str(part) for part in parts)
    return "SIG_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _graph_relations():
    path = INTERIM_DIR / "graph" / "relations.csv"
    if not path.exists():
        return set()
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    relations = set()
    for row in frame.to_dict("records"):
        if row.get("relation_type") not in {"COLLABORATED_WITH", "DISPUTED_WITH", "AMBASSADOR_OF"}:
            continue
        a, b = row.get("source_entity_id", ""), row.get("target_entity_id", "")
        if row["relation_type"] != "AMBASSADOR_OF":
            a, b = sorted((a, b))
        if a and b:
            relations.add((a, row["relation_type"], b))
    return relations


def _sentences(text):
    return [(i + 1, sentence.strip()) for i, sentence in enumerate(re.split(r"(?<=[.!?])\s+|\n+", text or "")) if sentence.strip()]


def _relation_pair(relation_type, left, left_type, right, right_type):
    if relation_type == "AMBASSADOR_OF":
        if (left_type, right_type) == ("Person", "Brand"):
            return left, right
        if (left_type, right_type) == ("Brand", "Person"):
            return right, left
    elif relation_type == "COLLABORATED_WITH":
        if left_type == right_type == "Person":
            return tuple(sorted((left, right)))
    elif relation_type == "DISPUTED_WITH":
        if left_type in {"Person", "Company"} and right_type in {"Person", "Company"}:
            return tuple(sorted((left, right)))
    return "", ""


def _role_detail(relation_type, sentence):
    if relation_type == "COLLABORATED_WITH":
        return "tín hiệu hợp tác; chỉ suy ra cạnh sau khi xác minh credit cùng tác phẩm"
    if relation_type == "AMBASSADOR_OF":
        return "đại sứ thương hiệu; cần xác minh vai trò và hai bên"
    # These are review hints, never adjudicated facts or automatic graph edges.
    for status, cues in (
        ("có phán quyết (cần kiểm tra)", ("phán quyết", "tuyên án")),
        ("đã hòa giải (cần kiểm tra)", ("hòa giải", "rút đơn kiện")),
        ("đang tranh chấp (cần kiểm tra)", ("tranh chấp", "khởi kiện", "khiếu nại bản quyền")),
        ("cáo buộc (cần kiểm tra)", ("cáo buộc", "tố cáo", "vi phạm bản quyền")),
    ):
        if any(_has_phrase(sentence, cue) for cue in cues):
            return status
    return ""


def build(write=True):
    terms_frame = pd.read_csv(TERMS_PATH, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    signal_terms = [(r["relation_type"], _accent_key(r["term"])) for r in terms_frame.to_dict("records") if r.get("term_group") == "signal" and r.get("term")]
    negations = [_accent_key(term) for r in terms_frame.to_dict("records") if r.get("term_group") == "negation" for term in r.get("query_terms", "").split("|")]
    uncertain = [_accent_key(term) for r in terms_frame.to_dict("records") if r.get("term_group") == "uncertain" for term in r.get("query_terms", "").split("|")]
    if not (INTERIM_DIR / "graph" / "entities.csv").exists():
        if write:
            _write(pd.DataFrame(columns=SIGNAL_COLUMNS))
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    entity_source = pd.read_csv(INTERIM_DIR / "graph" / "entities.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    # Detect relations between artists and graph-backed companies, shows, or events.
    entities = entity_source[entity_source["entity_type"].isin({"Person", "Group", "Company", "Show", "Event", "Brand"})].copy().fillna("")
    if entities.empty:
        if write:
            _write(pd.DataFrame(columns=SIGNAL_COLUMNS))
        print("Không có Person/Group trong graph để dò tín hiệu.")
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    term_rows = web._terms(entities.to_dict("records"))
    matcher = web._matcher(term_rows)
    exact_names = {}
    for entity_id, name, _ in term_rows:
        exact_names.setdefault(entity_id, set()).add((name, _accent_key(name)))
    name_owners = {}
    for entity_id, names in exact_names.items():
        for _, name_key in names:
            name_owners.setdefault(name_key, set()).add(entity_id)
    entity_names = entities.set_index("entity_id")["canonical_name"].to_dict()
    graph_relations = _graph_relations()
    docs = pd.DataFrame(web._read_docs()).fillna("")
    if docs.empty:
        if write:
            _write(pd.DataFrame(columns=SIGNAL_COLUMNS))
        print("Chưa có tài liệu web để dò tín hiệu.")
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    for idx, doc in docs.iterrows():
        if not doc.get("published_at_source") and doc.get("raw_html_path"):
            try:
                with (web.ROOT / doc["raw_html_path"]).open("rb") as html_file:
                    page = html_file.read(100_000).decode("utf-8", errors="replace")
                raw_date, source, published, conflict = web._page_publication_dates(page)
                docs.at[idx, "published_at_raw"] = raw_date
                docs.at[idx, "published_at_source"] = source
                docs.at[idx, "published_at"] = published
                docs.at[idx, "published_at_conflict"] = conflict
            except OSError:
                pass
    for column in ("published_at", "published_at_source", "published_at_conflict", "collected_at", "content_hash", "document_status"):
        if column not in docs:
            docs[column] = ""
    docs = docs[~docs["document_status"].isin({"loại bỏ"})]
    docs["published_date"] = docs["published_at"].map(web._date)
    if "published_at_source" in docs:
        docs = docs[docs["published_at_source"].ne("") & docs["published_at_conflict"].eq("")]
    if "crawl_relevance_status" in docs:
        docs = docs[docs["crawl_relevance_status"].ne("không liên quan")]
    docs = docs[docs["published_date"].map(lambda d: bool(d and PERIOD_START.isoformat() <= d <= PERIOD_END.isoformat()))]
    # Preserve signals from every distinct input URL, including URLs that
    # resolve to identical content. Graph-level relation dedup stays separate.

    found = []
    for doc in docs.to_dict("records"):
        content = unicodedata.normalize("NFC", doc.get("content", ""))
        title = unicodedata.normalize("NFC", doc.get("title", ""))
        lead = web._lead_text(content)
        # Inspect each sentence in the full extracted body, including documents queued for review.
        text = title + "\n" + content
        for location, sentence in _sentences(text):
            normalized = _accent_key(sentence)
            relation_types = {rtype for rtype, cue in signal_terms if cue and _has_phrase(sentence, cue)}
            if not relation_types:
                continue
            rough_matches = web._matches(sentence, matcher, allow_single_word=True)
            matched = _exact_entity_matches(sentence, rough_matches, exact_names, name_owners)
            if len(matched) < 2 or len(matched) > 4:
                continue
            caution = any(term and _has_phrase(sentence, term) for term in negations + uncertain)
            for i, left in enumerate(matched):
                for right in matched[i + 1:]:
                    left_type = entities.loc[entities["entity_id"] == left, "entity_type"].iloc[0]
                    right_type = entities.loc[entities["entity_id"] == right, "entity_type"].iloc[0]
                    for relation_type in relation_types:
                        a, b = _relation_pair(relation_type, left, left_type, right, right_type)
                        if not a:
                            continue
                        role_detail = _role_detail(relation_type, sentence)
                        weak_dispute = relation_type == "DISPUTED_WITH" and not role_detail
                        needs_review = caution or weak_dispute
                        signal_id = _stable_id(doc.get("document_id", ""), a, relation_type, b, location)
                        found.append({
                            "signal_id": signal_id, "document_id": doc.get("document_id", ""),
                            "entity_a_id": a, "entity_a_name": entity_names.get(a, ""),
                            "entity_b_id": b, "entity_b_name": entity_names.get(b, ""),
                            "relation_type": relation_type,
                            "relation_already_in_graph": "có" if (a, relation_type, b) in graph_relations else "không",
                            "title": title, "url": doc.get("url", ""), "source_name": doc.get("source_name", ""),
                            "published_at": doc.get("published_date", ""), "event_date": "", "quote": sentence,
                            "sentence_location": f"câu {location}",
                            "review_status": "cần kiểm tra" if needs_review else "ứng viên",
                            "query_status": "không tự query: cần duyệt tín hiệu" if needs_review else "chờ query",
                            "review_note": "cụm phủ định/không chắc chắn" if caution else ("chưa có tranh chấp/cáo buộc công khai rõ ràng" if weak_dispute else "ứng viên; cần kiểm tra chủ thể và ngữ cảnh"),
                            "role_detail": role_detail, "extraction_method": "rule-based; human review required",
                            "document_content_hash": doc.get("content_hash", ""), "reviewed_content_hash": "",
                        })

    fresh = pd.DataFrame(found, columns=SIGNAL_COLUMNS)
    if not fresh.empty:
        fresh = fresh.drop_duplicates("signal_id", keep="first")
    old = pd.DataFrame()
    if OUT_PATH.exists():
        old = pd.read_csv(OUT_PATH, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if not old.empty:
        old = old.drop_duplicates("signal_id", keep="last").set_index("signal_id")
        for idx, row in fresh.iterrows():
            prior = old.loc[row["signal_id"]] if row["signal_id"] in old.index else None
            if prior is None:
                continue
            prior = prior.to_dict()
            was_reviewed = prior.get("review_status") not in {"", "ứng viên"}
            previous_hash = prior.get("reviewed_content_hash") or (prior.get("document_content_hash") if was_reviewed else "")
            changed_content = bool(prior.get("document_content_hash") and prior["document_content_hash"] != row["document_content_hash"])
            if changed_content or (previous_hash and previous_hash != row["document_content_hash"]):
                fresh.at[idx, "review_status"] = "cần kiểm tra lại"
                fresh.at[idx, "query_status"] = "chờ duyệt lại nội dung"
                fresh.at[idx, "review_note"] = "nội dung tài liệu đổi sau lần duyệt"
            else:
                for col in ("review_status", "query_status", "review_note", "event_date"):
                    if prior.get(col):
                        fresh.at[idx, col] = prior[col]
                fresh.at[idx, "reviewed_content_hash"] = previous_hash
        current_ids = set(fresh["signal_id"])
        stale_rows = []
        current_doc_hashes = docs.set_index("document_id")["content_hash"].to_dict() if "document_id" in docs else {}
        for signal_id, prior in old.iterrows():
            prior = prior.to_dict()
            if signal_id in current_ids or (prior.get("review_status") in {"", "ứng viên"} and prior.get("query_status") in {"", "chờ query"}):
                continue
            if prior.get("document_id") not in current_doc_hashes:
                continue
            prior["review_status"] = "cần kiểm tra lại"
            prior["query_status"] = "chờ duyệt lại nội dung"
            prior["review_note"] = "tín hiệu cũ không còn khớp nội dung hiện tại"
            stale_rows.append(prior)
        if stale_rows:
            fresh = pd.concat([fresh, pd.DataFrame(stale_rows)], ignore_index=True)
    if write:
        _write(fresh)
    if write:
        print(f"Đã phát hiện {len(fresh)} tín hiệu quan hệ → {OUT_PATH}")
    else:
        queryable = int(((fresh["review_status"] == "ứng viên") & (fresh["query_status"] == "chờ query")).sum()) if not fresh.empty else 0
        print(f"Dry-run: {len(fresh)} tín hiệu, {queryable} đủ điều kiện tạo query; chưa ghi tệp.")
    return fresh


def _write(frame):
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    frame.reindex(columns=SIGNAL_COLUMNS).to_csv(OUT_PATH, index=False, encoding="utf-8-sig")


def update_query_status(signal_id, status):
    if not OUT_PATH.exists():
        return
    frame = pd.read_csv(OUT_PATH, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if "signal_id" not in frame:
        return
    frame.loc[frame["signal_id"] == signal_id, "query_status"] = status
    _write(frame)
