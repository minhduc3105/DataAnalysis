import random
import re
import unicodedata
import json
from datetime import datetime, timezone

import pandas as pd

from .config import INTERIM_DIR
from .model_contract import RELATION_SIGNATURES
from .graphdb import connect

GOLD_DIR = INTERIM_DIR.parent / "gold"
GRAPH_DIR = INTERIM_DIR / "graph"
ARTICLES = INTERIM_DIR.parent / "processed" / "web" / "articles_ready.csv"
SEED = 42
N_RELATIONS = 200
N_SENTENCES = 100
MIN_PER_TYPE = 8
OVERLAP = 0.2
MAX_NGRAM = 6
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ỹ\"“'‘(])")
PLATFORM = {"DOC_YT": "YouTube", "DOC_SP": "Spotify", "DOC_WEB": "Báo chí"}
LABEL_COLUMNS = ["label_huy", "label_duc", "correct_relation_type", "note"]


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")


def _annotators(n: int, rng: random.Random) -> list[str]:
    both = round(n * OVERLAP)
    rest = ["Huy" if i % 2 == 0 else "Đức" for i in range(n - both)]
    out = ["Cả hai"] * both + rest
    rng.shuffle(out)
    return out


def _allocate(counts: pd.Series, total: int) -> dict[str, int]:
    base = {t: min(c, MIN_PER_TYPE) for t, c in counts.items()}
    left = total - sum(base.values())
    spare = {t: c - base[t] for t, c in counts.items() if c > base[t]}
    pool = sum(spare.values())
    extra = {t: int(left * s / pool) for t, s in spare.items()}
    for t in sorted(spare, key=lambda t: -spare[t])[: left - sum(extra.values())]:
        extra[t] += 1
    return {t: base[t] + extra.get(t, 0) for t in counts.index}


def sample_relations(rng: random.Random) -> pd.DataFrame:
    rel = _read(GRAPH_DIR / "relations.csv")
    ev = _read(GRAPH_DIR / "evidence.csv").drop_duplicates("relation_id")
    quota = _allocate(rel.relation_type.value_counts(), N_RELATIONS)
    picked = pd.concat([rel[rel.relation_type == t].sample(n=k, random_state=SEED) for t, k in quota.items() if k])
    picked = picked.merge(ev[["relation_id", "document_id", "quote", "url", "extraction_method"]], on="relation_id", how="left")
    picked = picked.sample(frac=1, random_state=SEED).reset_index(drop=True)
    picked.insert(0, "gold_id", [f"GR_{i:03d}" for i in range(1, len(picked) + 1)])
    picked.insert(1, "annotator", _annotators(len(picked), rng))
    picked["platform"] = picked.document_id.str.extract(r"^(DOC_[A-Z]+)")[0].map(PLATFORM).fillna("")
    cols = ["gold_id", "annotator", "relation_id", "source_name", "relation_type", "target_name", "role_detail", "is_derived", "platform", "quote", "url", "extraction_method"]
    return picked[cols].assign(**{c: "" for c in LABEL_COLUMNS})


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", text))


def _dictionary() -> dict[tuple[str, ...], tuple[str, str]]:
    ent = _read(GRAPH_DIR / "entities.csv")
    out: dict[tuple[str, ...], tuple[str, str]] = {}
    for e in ent.itertuples():
        for name in [e.canonical_name, *e.aliases.split(" | ")]:
            toks = tuple(t.casefold() for t in _tokens(name))
            # Tên bài/album một chữ ("Yêu", "Tình") trùng từ thường trong câu, gợi ý sẽ nhiễu.
            if not toks or len(toks) > MAX_NGRAM or len("".join(toks)) < 3 or (e.entity_type in {"Song", "Album"} and len(toks) < 2):
                continue
            out.setdefault(toks, (e.canonical_name, e.entity_type))
    return out


def _matches(sentence: str, vocab: dict) -> list[tuple[str, str]]:
    raw = _tokens(sentence)
    toks = [t.casefold() for t in raw]
    found, i = [], 0
    while i < len(toks):
        for n in range(min(MAX_NGRAM, len(toks) - i), 0, -1):
            # Chỉ nhận cụm viết hoa: "anh Dũng" (ông anh) không phải nghệ sĩ Anh Dũng.
            hit = vocab.get(tuple(toks[i : i + n])) if all(t[0].isupper() or t[0].isdigit() for t in raw[i : i + n]) else None
            if hit:
                found.append(hit)
                i += n
                break
        else:
            i += 1
    return list(dict.fromkeys(found))


def sample_sentences(rng: random.Random) -> pd.DataFrame:
    art = _read(ARTICLES)
    vocab = _dictionary()
    candidates = []
    for a in art.sample(frac=1, random_state=SEED).itertuples():
        text = a.body_text or a.content
        sents = [s.strip() for s in SENTENCE_SPLIT.split(text) if 40 <= len(s.strip()) <= 400]
        rng.shuffle(sents)
        for s in sents:
            hits = _matches(s, vocab)
            if len(hits) >= 2 and any(t in {"Person", "Group"} for _, t in hits):
                candidates.append({"document_id": a.document_id, "source_name": a.source_name, "published_at": a.published_at_iso or a.published_at, "url": a.final_url or a.url, "sentence": s, "suggested_entities": "; ".join(f"{n}|{t}" for n, t in hits)})
                break
        if len(candidates) >= N_SENTENCES:
            break
    df = pd.DataFrame(candidates)
    df.insert(0, "gold_id", [f"GS_{i:03d}" for i in range(1, len(df) + 1)])
    df.insert(1, "annotator", _annotators(len(df), rng))
    return df.assign(entities_huy="", relations_huy="", entities_duc="", relations_duc="", note="")


def sample(force: bool = False) -> None:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    for name, build in [("gold_relations.csv", sample_relations), ("gold_sentences.csv", sample_sentences)]:
        path = GOLD_DIR / name
        # Chạy lại sẽ ghi đè nhãn đã gán tay, nên phải có --force.
        if path.exists() and not force:
            print(f"Bỏ qua {path} (đã có, có thể đã gán nhãn; dùng --force để tạo lại)")
            continue
        df = build(rng)
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"→ {path} ({len(df)} dòng; {df.annotator.value_counts().to_dict()})")


def multi_hop_duc(count: int = 15, force: bool = False) -> Path:
    """Create evidence-backed, versioned question candidates from the current Neo4j graph."""
    out = GOLD_DIR / "multihop_duc.jsonl"
    if out.exists() and not force:
        raise FileExistsError(f"{out} đã tồn tại; giữ nguyên nhãn tay. Dùng --force để ghi đè.")
    if count < 1 or count > 100:
        raise ValueError("count phải từ 1 đến 100")
    from .analysis import _graph_version

    templates = [
        "Có những bằng chứng nào nối {start} với {target}? Nêu chuỗi quan hệ ngắn nhất.",
        "Vì sao {start} có liên quan tới {target} trong đồ thị? Trình bày từng bước có nguồn.",
        "Tìm đường đi có bằng chứng giữa {start} và {target}; qua những thực thể nào?",
        "Dựa trên các bài đã lưu, chuỗi quan hệ ngắn nhất giữa {start} và {target} là gì?",
        "{start} liên hệ với {target} qua những quan hệ và nguồn tin nào?",
    ]
    driver = connect()
    questions = []
    try:
        with driver.session() as session:
            graph_version, _, _ = _graph_version(session)
            candidates = [r.data() for r in session.run("""
                MATCH (n:Entity) WHERE n:Person OR n:Group
                RETURN n.entity_id AS id,n.name AS name
                ORDER BY coalesce(n.pagerank,0) DESC,n.entity_id LIMIT 600
            """)]
            rng = random.Random(42)
            rng.shuffle(candidates)
            seen_pairs = set()
            for start in candidates:
                paths = [r.data() for r in session.run("""
                    MATCH (a:Entity {entity_id:$id})
                    MATCH p=(a)-[*2..3]-(b:Entity)
                    WHERE a.entity_id < b.entity_id
                      AND all(r IN relationships(p) WHERE type(r) IN $types AND EXISTS {
                        MATCH (ev:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(:Document)
                      })
                    RETURN [n IN nodes(p) | {id:n.entity_id,name:n.name,type:[l IN labels(n) WHERE l<>'Entity'][0]}] AS nodes,
                           [r IN relationships(p) | {relation_id:r.relation_id,type:type(r),source:startNode(r).entity_id,target:endNode(r).entity_id}] AS edges
                    ORDER BY length(p),reduce(score=0.0,n IN nodes(p) | score+coalesce(n.pagerank,0.0)) DESC
                    LIMIT 8
                """, id=start["id"], types=sorted(RELATION_SIGNATURES))]
                for path in paths:
                    nodes, edges = path["nodes"], path["edges"]
                    pair = (nodes[0]["id"], nodes[-1]["id"])
                    if len(edges) < 2 or pair in seen_pairs:
                        continue
                    evidence = []
                    for edge in edges:
                        source_rows = [r.data() for r in session.run("""
                            MATCH (ev:Evidence {relation_id:$id})-[:FROM_DOCUMENT]->(d:Document)
                            WHERE ev.review_status='accepted'
                            RETURN ev.evidence_id AS evidence_id,ev.quote AS quote,d.document_id AS document_id,
                                   d.title AS title,d.url AS url,d.source_name AS source,d.published_at AS published_at
                            ORDER BY d.published_at DESC LIMIT 2
                        """, id=edge["relation_id"])]
                        if not source_rows:
                            evidence = []
                            break
                        evidence.append({"relation_id": edge["relation_id"], "sources": source_rows})
                    if len(evidence) != len(edges):
                        continue
                    seen_pairs.add(pair)
                    q = templates[len(questions) % len(templates)].format(start=nodes[0]["name"], target=nodes[-1]["name"])
                    questions.append({
                        "question_id": f"DUC_MH_{len(questions) + 1:02d}",
                        "question": q,
                        "expected_answer": " → ".join(n["name"] for n in nodes),
                        "expected_path": {"nodes": nodes, "edges": edges},
                        "evidence": evidence,
                        "graph_version": graph_version,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "review_status": "candidate_needs_duc_review",
                    })
                    if len(questions) >= count:
                        break
                if len(questions) >= count:
                    break
    finally:
        driver.close()
    if len(questions) < count:
        raise RuntimeError(f"Chỉ tìm được {len(questions)}/{count} đường đi 2–3 bước có bằng chứng được duyệt. Tệp chưa được ghi; kiểm tra độ phủ Evidence hoặc thử tăng dữ liệu.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in questions) + "\n", encoding="utf-8")
    print(f"Đã tạo {len(questions)} câu hỏi multi-hop ứng viên: {out}; graph_version={questions[0]['graph_version']}. Đức rà soát nội dung trước khi dùng đánh giá.")
    return out
