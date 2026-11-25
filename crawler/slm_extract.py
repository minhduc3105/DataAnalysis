import hashlib
import json
import os
import random
import time

import pandas as pd
import requests

from .common import normalize_name
from .gold import SEED
from .model_contract import SCHEMA_VERSION, validate_extraction
from .preprocess import OUT_DIR as PREP_DIR, load_articles, load_dictionary, preprocess_document
from .slm import NUM_CTX, PROMPT_VERSION, chat, validate

MODEL = os.getenv("SLM_MODEL", "qwen3:8b")
OUT_DIR = PREP_DIR.parent
# SLM không trả điểm tự tin; đây là quy ước, không phải xác suất: bằng chứng nguyên văn 0.9, phải lùi về cả câu 0.6.
CONFIDENCE_VERBATIM, CONFIDENCE_REPAIRED = 0.9, 0.6
REVIEW_ENTITY_DOCS, REVIEW_RELATIONS = 5, 50


def model_version(model: str = MODEL) -> str:
    return f"{model}+prompt-{PROMPT_VERSION}"


class SentenceCache:
    """Kết quả SLM theo từng câu, ghi ngay sau mỗi câu: dừng ngang rồi chạy lại sẽ không gọi lại câu đã xong."""

    def __init__(self, model: str = MODEL):
        self.model = model
        self.path = OUT_DIR / f"slm_cache_{model.replace(':', '_')}_{PROMPT_VERSION}.jsonl"
        self.data = {}
        if self.path.exists():
            # Chạm num_predict là lỗi tất định (temperature 0) nên giữ lại; JSON lỗi vì lý do khác thì lần sau gọi lại.
            self.data = {d["key"]: d for d in map(json.loads, self.path.read_text(encoding="utf-8").splitlines()) if d.get("valid") or d.get("done_reason") == "length"}
        self.calls = 0

    def get(self, sentence: str) -> dict:
        key = hashlib.sha1(sentence.encode("utf-8")).hexdigest()
        if key not in self.data:
            try:
                out = {"key": key, "sentence": sentence, **chat(self.model, sentence, num_ctx=NUM_CTX)}
            except requests.RequestException as exc:
                return {"parsed": {"entities": [], "relations": []}, "valid": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
            self.calls += 1
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
            self.data[key] = out
        return self.data[key]


def locate(sentence: str, name: str) -> tuple[int, int] | None:
    name = name.strip()
    if not name:
        return None
    i = sentence.find(name)
    if i < 0 and len(sentence.casefold()) == len(sentence):
        i = sentence.casefold().find(name.casefold())
    return (i, i + len(name)) if i >= 0 else None


def extract_document(document_id: str, text: str, ctx: tuple, cache: SentenceCache) -> tuple[dict, list[dict]]:
    vocab, reject, allow_lower = ctx
    sentences, _ = preprocess_document(document_id, text, vocab, reject, allow_lower)
    entities, relations, log = [], [], []
    for s in (x for x in sentences if x["is_candidate"]):
        out = cache.get(s["sentence"])
        if not out["valid"]:
            reason = out.get("error") or ("SLM lặp, chạm giới hạn token đầu ra" if out.get("done_reason") == "length" else "JSON lỗi")
            log.append({"document_id": document_id, "sentence_id": s["sentence_id"], "kind": "sentence", "item": s["sentence"][:120], "reason": reason})
            continue
        parsed = out["parsed"]
        local = {}
        for e in parsed.get("entities", []):
            span = locate(s["sentence"], e.get("text", ""))
            if not span:
                log.append({"document_id": document_id, "sentence_id": s["sentence_id"], "kind": "mention", "item": e.get("text", ""), "reason": "không tìm thấy trong câu"})
                continue
            key = normalize_name(e["text"])
            if key in local:
                continue
            start, end = s["start"] + span[0], s["start"] + span[1]
            mid = f"m{len(entities) + 1:04d}"
            entities.append({"mention_id": mid, "text": text[start:end], "type": e["type"], "start": start, "end": end})
            local[key] = mid
        kept = validate(parsed, s["sentence"])
        kept_keys = {(k["head"], k["type"], k["tail"]) for k in kept}
        for x in parsed.get("relations", []):
            if (x.get("head"), x.get("type"), x.get("tail")) not in kept_keys:
                log.append({"document_id": document_id, "sentence_id": s["sentence_id"], "kind": "relation", "item": f"{x.get('head')}|{x.get('type')}|{x.get('tail')}", "reason": "hậu kiểm loại (sai kiểu nút, tên không có trong câu hoặc head = tail)"})
        for r in kept:
            head, tail = local.get(normalize_name(r["head"])), local.get(normalize_name(r["tail"]))
            if not head or not tail:
                log.append({"document_id": document_id, "sentence_id": s["sentence_id"], "kind": "relation", "item": f"{r['head']}|{r['type']}|{r['tail']}", "reason": "head/tail không khớp mention nào"})
                continue
            relations.append({
                "head_mention_id": head, "type": r["type"], "tail_mention_id": tail, "evidence": r["evidence"],
                "confidence": CONFIDENCE_REPAIRED if r.get("evidence_repaired") else CONFIDENCE_VERBATIM,
            })
    result = {"document_id": document_id, "schema_version": SCHEMA_VERSION, "model_version": model_version(cache.model), "entities": entities, "relations": relations}
    return result, log


def _review_files(results: list[dict], texts: dict[str, str], tag: str, seed: int) -> None:
    rng = random.Random(seed)
    ent_rows, rel_rows = [], []
    for res in results[:REVIEW_ENTITY_DOCS]:
        for e in res["entities"]:
            ctx = texts[res["document_id"]][max(0, e["start"] - 60) : e["end"] + 60].replace("\n", " ")
            ent_rows.append({"document_id": res["document_id"], "mention_id": e["mention_id"], "text": e["text"], "type": e["type"], "context": ctx, "label_huy": "", "note": ""})
    for res in results:
        by_id = {e["mention_id"]: e for e in res["entities"]}
        for r in res["relations"]:
            h, t = by_id[r["head_mention_id"]], by_id[r["tail_mention_id"]]
            rel_rows.append({"document_id": res["document_id"], "head": h["text"], "head_type": h["type"], "type": r["type"], "tail": t["text"], "tail_type": t["type"], "evidence": r["evidence"], "confidence": r["confidence"], "label_huy": "", "correct_type": "", "note": ""})
    rel_rows = rng.sample(rel_rows, min(REVIEW_RELATIONS, len(rel_rows)))
    pd.DataFrame(ent_rows).to_csv(OUT_DIR / f"review_entities_{tag}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(rel_rows).to_csv(OUT_DIR / f"review_relations_{tag}.csv", index=False, encoding="utf-8-sig")


def run(docs: int | None = 20, seed: int = SEED, model: str = MODEL) -> None:
    articles, everything = load_articles(docs, seed)
    vocab, reject, allow_lower, _ = load_dictionary(everything.text)
    cache = SentenceCache(model)
    tag = f"sample{docs}" if docs else "all"
    texts = dict(zip(articles.document_id, articles.text))
    results, log, t0 = [], [], time.time()
    for i, a in enumerate(articles.itertuples(), 1):
        res, doc_log = extract_document(a.document_id, a.text, (vocab, reject, allow_lower), cache)
        results.append(res)
        log += doc_log
        print(f"  {i}/{len(articles)} {a.document_id}: {len(res['entities'])} mention, {len(res['relations'])} quan hệ (đã gọi SLM {cache.calls} câu, {time.time() - t0:.0f}s)")
    errors = [f"{r['document_id']}: {e}" for r in results for e in validate_extraction(r, texts)]
    path = OUT_DIR / f"extractions_{tag}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    pd.DataFrame(log, columns=["document_id", "sentence_id", "kind", "item", "reason"]).to_csv(OUT_DIR / f"extraction_log_{tag}.csv", index=False, encoding="utf-8-sig")
    _review_files(results, texts, tag, seed)
    n_ent, n_rel = sum(len(r["entities"]) for r in results), sum(len(r["relations"]) for r in results)
    lost = pd.Series([x["kind"] for x in log]).value_counts().to_dict() if log else {}
    repaired = sum(r["confidence"] == CONFIDENCE_REPAIRED for res in results for r in res["relations"])
    print(f"\n{model_version(model)}: {len(results)} bài → {n_ent} mention, {n_rel} quan hệ ({repaired} quan hệ phải lùi bằng chứng về cả câu)")
    print(f"Bị loại (ghi trong extraction_log_{tag}.csv): {lost}")
    print(f"Vi phạm hợp đồng (validate_extraction): {len(errors)}")
    for e in errors[:10]:
        print("  LỖI", e)
    print(f"Đã ghi {path}, review_entities_{tag}.csv ({REVIEW_ENTITY_DOCS} bài đầu), review_relations_{tag}.csv ({REVIEW_RELATIONS} quan hệ ngẫu nhiên)")
    if errors:
        raise SystemExit(1)
