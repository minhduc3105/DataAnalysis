import json
import os
import time

import pandas as pd
import requests

from .common import normalize_name
from .gold import GOLD_DIR

OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
SENTENCES = GOLD_DIR / "gold_sentences.csv"
ENTITY_TYPES = ["Person", "Group", "Song", "Album", "Company", "Show", "Event", "Brand"]
RELATION_TYPES = [
    "PERFORMED", "FEATURED_ON", "COMPOSED", "PRODUCED", "RELEASED_BY", "TRACK_OF", "MEMBER_OF",
    "CONTESTANT_ON", "JUDGE_ON", "PERFORMED_AT", "ORGANIZED_BY", "AMBASSADOR_OF", "COLLABORATED_WITH", "DISPUTED_WITH",
]
UNDIRECTED = {"COLLABORATED_WITH", "DISPUTED_WITH"}
ARTIST = {"Person", "Group"}
SIGNATURE = {
    "PERFORMED": (ARTIST, {"Song"}), "FEATURED_ON": (ARTIST, {"Song"}), "COMPOSED": ({"Person"}, {"Song"}),
    "PRODUCED": ({"Person"}, {"Song"}), "RELEASED_BY": ({"Song", "Album"}, {"Company"}), "TRACK_OF": ({"Song"}, {"Album"}),
    "MEMBER_OF": ({"Person"}, {"Group"}), "CONTESTANT_ON": ({"Person"}, {"Show"}), "JUDGE_ON": ({"Person"}, {"Show"}),
    "PERFORMED_AT": (ARTIST, {"Show", "Event"}), "ORGANIZED_BY": ({"Show", "Event"}, {"Company"}), "AMBASSADOR_OF": (ARTIST, {"Brand"}),
    "COLLABORATED_WITH": (ARTIST, ARTIST), "DISPUTED_WITH": (ARTIST | {"Company"}, ARTIST | {"Company"}),
}

SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "type": {"type": "string", "enum": ENTITY_TYPES}}, "required": ["text", "type"]}},
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"head": {"type": "string"}, "type": {"type": "string", "enum": RELATION_TYPES}, "tail": {"type": "string"}, "evidence": {"type": "string"}},
                "required": ["head", "type", "tail", "evidence"],
            },
        },
    },
    "required": ["entities", "relations"],
}

SYSTEM = """Bạn trích xuất thông tin về ngành âm nhạc Việt Nam từ một câu báo chí. Trả về JSON theo schema.

Thực thể (chỉ người/tổ chức/tác phẩm thuộc ngành âm nhạc, giải trí; bỏ quan chức, địa danh, người ngoài ngành):
Person (ca sĩ, rapper, nhạc sĩ, producer), Group (nhóm nhạc, ban nhạc), Song (bài hát), Album (album, EP), Company (công ty giải trí, hãng đĩa), Show (chương trình truyền hình, gameshow), Event (concert, lễ trao giải), Brand (thương hiệu).
Ghi "text" đúng như cách viết trong câu.

Quan hệ (chỉ khi CHÍNH CÂU NÓI RA; cùng xuất hiện không đủ). head và tail phải là "text" của thực thể đã liệt kê:
PERFORMED Person/Group→Song: trình bày | FEATURED_ON Person/Group→Song: khách mời feat.
COMPOSED Person→Song: sáng tác | PRODUCED Person→Song: sản xuất, hòa âm
RELEASED_BY Song→Company | TRACK_OF Song→Album | MEMBER_OF Person→Group
CONTESTANT_ON Person→Show: thí sinh | JUDGE_ON Person→Show: giám khảo, huấn luyện viên
PERFORMED_AT Person/Group→Show/Event: biểu diễn, khách mời | ORGANIZED_BY Show/Event→Company
AMBASSADOR_OF Person/Group→Brand | COLLABORATED_WITH Person↔Person: cùng làm một sản phẩm cụ thể
DISPUTED_WITH Person/Group/Company↔Person/Group/Company: tranh chấp, kiện tụng, cáo buộc công khai (tin đồn không tính)
"evidence" là đoạn ngắn chép nguyên văn từ câu. Không có gì thì trả danh sách rỗng."""

FEW_SHOT = [
    (
        "Ca khúc See Tình do Hoàng Thùy Linh trình bày, Tiên Cookie sáng tác, được phát hành bởi Sony Music Vietnam.",
        {
            "entities": [{"text": "See Tình", "type": "Song"}, {"text": "Hoàng Thùy Linh", "type": "Person"}, {"text": "Tiên Cookie", "type": "Person"}, {"text": "Sony Music Vietnam", "type": "Company"}],
            "relations": [
                {"head": "Hoàng Thùy Linh", "type": "PERFORMED", "tail": "See Tình", "evidence": "See Tình do Hoàng Thùy Linh trình bày"},
                {"head": "Tiên Cookie", "type": "COMPOSED", "tail": "See Tình", "evidence": "Tiên Cookie sáng tác"},
                {"head": "See Tình", "type": "RELEASED_BY", "tail": "Sony Music Vietnam", "evidence": "được phát hành bởi Sony Music Vietnam"},
            ],
        },
    ),
    (
        "Đức Phúc vui vẻ chụp hình kỉ niệm cùng Erik sau đêm nhạc.",
        {"entities": [{"text": "Đức Phúc", "type": "Person"}, {"text": "Erik", "type": "Person"}], "relations": []},
    ),
]


def chat(model: str, sentence: str, timeout: int = 300) -> dict:
    messages = [{"role": "system", "content": SYSTEM}]
    for s, out in FEW_SHOT:
        messages += [{"role": "user", "content": s}, {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}]
    messages.append({"role": "user", "content": sentence})
    body = {"model": model, "messages": messages, "format": SCHEMA, "stream": False, "think": False, "options": {"temperature": 0, "num_ctx": 4096}}
    t0 = time.time()
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    raw = data["message"]["content"]
    try:
        parsed, valid = json.loads(raw), True
    except json.JSONDecodeError:
        parsed, valid = {"entities": [], "relations": []}, False
    return {
        "raw": raw, "parsed": parsed, "valid": valid, "seconds": round(time.time() - t0, 2),
        "tokens_per_second": round(data.get("eval_count", 0) / max(data.get("eval_duration", 1) / 1e9, 1e-9), 1),
    }


def validate(parsed: dict, sentence: str) -> list[dict]:
    """Hậu kiểm: giữ quan hệ có head/tail là thực thể đã trích, đúng kiểu nút theo SIGNATURE và câu trích có thật trong câu."""
    types = {normalize_name(e.get("text", "")): e.get("type") for e in parsed.get("entities", [])}
    flat = normalize_name(sentence)
    kept = []
    for x in parsed.get("relations", []):
        h, t, rt = normalize_name(x.get("head", "")), normalize_name(x.get("tail", "")), x.get("type", "")
        heads, tails = SIGNATURE.get(rt, (set(), set()))
        ok_types = types.get(h) in heads and types.get(t) in tails
        if rt in UNDIRECTED:
            ok_types = ok_types or (types.get(t) in heads and types.get(h) in tails)
        if h and t and h != t and ok_types and normalize_name(x.get("evidence", "")) in flat:
            kept.append(x)
    return kept


def _cache(model: str):
    return GOLD_DIR / f"slm_predictions_{model.replace(':', '_').replace('/', '_')}.jsonl"


def predict(model: str) -> list[dict]:
    rows = pd.read_csv(SENTENCES, encoding="utf-8-sig", dtype=str).fillna("")
    path = _cache(model)
    done = {}
    if path.exists():
        done = {d["gold_id"]: d for d in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
    with path.open("a", encoding="utf-8") as f:
        for i, r in enumerate(rows.itertuples(), 1):
            if r.gold_id in done:
                continue
            out = {"gold_id": r.gold_id, "model": model, **chat(model, r.sentence)}
            done[r.gold_id] = out
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
            print(f"  {model} {i}/{len(rows)} {out['seconds']}s {'JSON ok' if out['valid'] else 'JSON lỗi'}")
    return [done[g] for g in rows.gold_id if g in done]


def _entities(cell: str) -> set[tuple[str, str]]:
    out = set()
    for part in cell.split(";"):
        bits = [b.strip() for b in part.split("|")]
        if len(bits) == 2 and bits[0] and bits[0].upper() != "NONE":
            out.add((normalize_name(bits[0]), bits[1]))
    return out


def _relations(cell: str) -> set[tuple[str, str, str]]:
    out = set()
    for part in cell.split(";"):
        bits = [b.strip() for b in part.split("|")]
        if len(bits) == 3 and bits[0].upper() != "NONE":
            h, t = normalize_name(bits[0]), normalize_name(bits[2])
            out.add((min(h, t), bits[1], max(h, t)) if bits[1] in UNDIRECTED else (h, bits[1], t))
    return out


def _gold(row) -> tuple[str, str] | None:
    # Huy gán toàn bộ 100 câu (quyết định 25/11); cột annotator chỉ còn là dấu vết lúc lấy mẫu.
    ent, rel = row.entities_huy, row.relations_huy
    return (ent, rel) if ent.strip() else None


def _prf(tp: int, n_pred: int, n_gold: int) -> tuple[float, float, float]:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    return round(p, 3), round(r, 3), round(2 * p * r / (p + r), 3) if p + r else 0.0


def score(name: str, preds: dict[str, tuple[set, set, set]], gold: dict[str, tuple[set, set]]) -> dict:
    tp = {"ent": 0, "ent_text": 0, "rel": 0}
    n = {"pe": 0, "ge": 0, "pr": 0, "gr": 0}
    for gid, (ge, gr) in gold.items():
        pe, pe_text, pr = preds.get(gid, (set(), set(), set()))
        tp["ent"] += len(pe & ge)
        tp["ent_text"] += len(pe_text & {t for t, _ in ge})
        tp["rel"] += len(pr & gr)
        n["pe"] += len(pe); n["ge"] += len(ge); n["pr"] += len(pr); n["gr"] += len(gr)
    pe, re_, fe = _prf(tp["ent"], n["pe"], n["ge"])
    _, _, fe_text = _prf(tp["ent_text"], n["pe"], n["ge"])
    pr, rr, fr = _prf(tp["rel"], n["pr"], n["gr"])
    return {"method": name, "sentences": len(gold), "entity_p": pe, "entity_r": re_, "entity_f1": fe, "entity_f1_ignore_type": fe_text, "relation_p": pr, "relation_r": rr, "relation_f1": fr}


def bench(models: list[str]) -> None:
    rows = pd.read_csv(SENTENCES, encoding="utf-8-sig", dtype=str).fillna("")
    gold = {r.gold_id: (_entities(g[0]), _relations(g[1])) for r in rows.itertuples() if (g := _gold(r))}
    sentence_of = dict(zip(rows.gold_id, rows.sentence))

    def rel_set(rels: list[dict]) -> set:
        out = set()
        for x in rels:
            h, t, rt = normalize_name(x.get("head", "")), normalize_name(x.get("tail", "")), x.get("type", "")
            out.add((min(h, t), rt, max(h, t)) if rt in UNDIRECTED else (h, rt, t))
        return out

    from .gold_eval import load_split

    split_of = load_split()
    parts = {name: {g: v for g, v in gold.items() if split_of.get(g) == name} for name in ("test", "dev")} if split_of else {"all": gold}

    def score_parts(name: str, preds: dict) -> list[dict]:
        return [{"split": part, **score(name, preds, sub)} for part, sub in parts.items()]

    results = []
    for model in models:
        print(f"Chạy {model} trên {len(rows)} câu (kết quả lưu ở {_cache(model).name})")
        out = predict(model)
        speed = pd.DataFrame(out)
        stats = {"json_valid": round(speed.valid.mean(), 3), "seconds_per_sentence": round(speed.seconds.median(), 2), "tokens_per_second": round(speed.tokens_per_second.median(), 1)}
        for label, use_validation in [("", False), (" + hậu kiểm", True)]:
            preds = {}
            for o in out:
                p = o["parsed"]
                ents = {(normalize_name(e.get("text", "")), e.get("type", "")) for e in p.get("entities", []) if e.get("text")}
                rels = validate(p, sentence_of[o["gold_id"]]) if use_validation else p.get("relations", [])
                preds[o["gold_id"]] = (ents, {e for e, _ in ents}, rel_set(rels))
            results += [{**r, **stats} for r in score_parts(model + label, preds)]
    base = {r.gold_id: (e := _entities(r.suggested_entities), {t for t, _ in e}, set()) for r in rows.itertuples()}
    results += [{**r, "json_valid": None, "seconds_per_sentence": None, "tokens_per_second": None} for r in score_parts("baseline từ điển (GĐ1)", base)]
    df = pd.DataFrame(results).sort_values("split", ascending=False, kind="stable")
    df.to_csv(GOLD_DIR / "slm_benchmark.csv", index=False, encoding="utf-8-sig")
    if not gold:
        print("Chưa có nhãn gold (cột entities_huy/entities_duc trống): mới lưu dự đoán, F1 sẽ tính khi gán nhãn xong.")
    print(df.to_string(index=False))
