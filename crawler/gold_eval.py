import math
import random

import pandas as pd

from .common import normalize_name
from .gold import GOLD_DIR, GRAPH_DIR, SEED
from .model_contract import ENTITY_TYPES, RELATION_SIGNATURES, UNDIRECTED

RELATIONS_FILE = GOLD_DIR / "gold_relations.csv"
SENTENCES_FILE = GOLD_DIR / "gold_sentences.csv"
SPLIT_FILE = GOLD_DIR / "gold_split.csv"
DEV_SHARE = 0.3
FEW_SHOT_OVERLAP = 0.3
LABELS = {"đúng", "sai", "không rõ"}
NOTE_CODES = {"ten_rac", "sai_nguoi", "sai_bai", "sai_loai_nut", "sai_loai", "sai_huong", "sai_mua", "mcn", "phan_phoi", "khong_co_quan_he", "khong_xac_minh"}
Z = 1.96


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")


def note_code(note: str) -> str:
    return note.split(":", 1)[0].strip()


def wilson(k: int, n: int) -> tuple[float, float]:
    if not n:
        return 0.0, 0.0
    p = k / n
    centre = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return round(centre - half, 4), round(centre + half, 4)


def check_relations(df: pd.DataFrame) -> list[str]:
    errors = []
    for r in df.itertuples():
        where = f"{r.gold_id}"
        if r.label_huy not in LABELS:
            errors.append(f"{where}: label_huy '{r.label_huy}' không thuộc {sorted(LABELS)}")
            continue
        if r.label_huy == "sai":
            if r.correct_relation_type not in RELATION_SIGNATURES and r.correct_relation_type != "NONE":
                errors.append(f"{where}: sai nhưng correct_relation_type '{r.correct_relation_type}' không phải loại hợp lệ hoặc NONE")
            if note_code(r.note) not in NOTE_CODES:
                errors.append(f"{where}: sai nhưng note không mở đầu bằng mã lỗi hợp lệ")
        elif r.correct_relation_type:
            errors.append(f"{where}: {r.label_huy} nhưng vẫn điền correct_relation_type")
        if r.label_huy == "không rõ" and note_code(r.note) not in NOTE_CODES:
            errors.append(f"{where}: không rõ nhưng note không mở đầu bằng mã lỗi hợp lệ")
    return errors


def parse_entities(cell: str) -> list[tuple[str, str]] | None:
    if cell.strip().upper() == "NONE":
        return []
    out = []
    for part in cell.split(";"):
        bits = [b.strip() for b in part.split("|")]
        if len(bits) != 2 or not bits[0]:
            return None
        out.append((bits[0], bits[1]))
    return out


def parse_relations(cell: str) -> list[tuple[str, str, str]] | None:
    if cell.strip().upper() == "NONE":
        return []
    out = []
    for part in cell.split(";"):
        bits = [b.strip() for b in part.split("|")]
        if len(bits) != 3 or not bits[0] or not bits[2]:
            return None
        out.append((bits[0], bits[1], bits[2]))
    return out


def _signature_ok(rtype: str, head_type: str, tail_type: str) -> bool:
    heads, tails = RELATION_SIGNATURES[rtype]
    if head_type in heads and tail_type in tails:
        return True
    return rtype in UNDIRECTED and tail_type in heads and head_type in tails


def check_sentences(df: pd.DataFrame) -> list[str]:
    errors = []
    for r in df.itertuples():
        where = r.gold_id
        ents, rels = parse_entities(r.entities_huy), parse_relations(r.relations_huy)
        if ents is None:
            errors.append(f"{where}: entities_huy sai cú pháp 'Tên|Loại; …' hoặc trống")
            continue
        if rels is None:
            errors.append(f"{where}: relations_huy sai cú pháp 'A|LOẠI|B; …' hoặc trống")
            continue
        sentence = normalize_name(r.sentence)
        types = {}
        for name, etype in ents:
            if etype not in ENTITY_TYPES:
                errors.append(f"{where}: loại thực thể '{etype}' không hợp lệ")
            if normalize_name(name) not in sentence:
                errors.append(f"{where}: thực thể '{name}' không có trong câu")
            types[normalize_name(name)] = etype
        for head, rtype, tail in rels:
            if rtype not in RELATION_SIGNATURES:
                errors.append(f"{where}: loại quan hệ '{rtype}' không hợp lệ")
                continue
            h, t = types.get(normalize_name(head)), types.get(normalize_name(tail))
            if h is None or t is None:
                errors.append(f"{where}: quan hệ {head}|{rtype}|{tail} dùng tên không có trong entities_huy")
            elif not _signature_ok(rtype, h, t):
                errors.append(f"{where}: {head}({h}) {rtype} {tail}({t}) sai kiểu nút hoặc hướng")
    return errors


def check() -> int:
    errors = check_relations(_read(RELATIONS_FILE)) + check_sentences(_read(SENTENCES_FILE))
    for e in errors:
        print(e)
    print(f"{len(errors)} lỗi định dạng nhãn" if errors else "Nhãn gold hợp lệ (gold_relations.csv, gold_sentences.csv)")
    return len(errors)


def precision_by_type(df: pd.DataFrame, population: dict[str, int]) -> tuple[pd.DataFrame, dict]:
    rows = []
    for rtype, g in df.groupby("relation_type"):
        correct, wrong, unclear = (g.label_huy == "đúng").sum(), (g.label_huy == "sai").sum(), (g.label_huy == "không rõ").sum()
        judged = correct + wrong
        low, high = wilson(correct, judged)
        rows.append({
            "relation_type": rtype, "graph_edges": population.get(rtype, 0), "sampled": len(g), "correct": correct, "wrong": wrong, "unclear": unclear,
            "precision": round(correct / judged, 4) if judged else None, "ci95_low": low, "ci95_high": high,
            "precision_unclear_as_wrong": round(correct / len(g), 4),
        })
    table = pd.DataFrame(rows).sort_values("graph_edges", ascending=False)
    judged = table[table.precision.notna()]
    weights = judged.graph_edges / judged.graph_edges.sum()
    weighted = float((weights * judged.precision).sum())
    # Phương sai phân tầng: mỗi loại cạnh là một tầng, lấy mẫu độc lập.
    var = float((weights**2 * judged.precision * (1 - judged.precision) / (judged.correct + judged.wrong)).sum())
    correct, total_judged = int(table.correct.sum()), int((table.correct + table.wrong).sum())
    summary = {
        "sampled": int(table.sampled.sum()), "correct": correct, "wrong": int(table.wrong.sum()), "unclear": int(table.unclear.sum()),
        "precision_micro": round(correct / total_judged, 4) if total_judged else None,
        "precision_micro_ci95": wilson(correct, total_judged),
        "precision_weighted": round(weighted, 4),
        "precision_weighted_ci95": (round(weighted - Z * math.sqrt(var), 4), round(min(1.0, weighted + Z * math.sqrt(var)), 4)),
        "precision_unclear_as_wrong": round(correct / int(table.sampled.sum()), 4),
    }
    return table, summary


def error_table(df: pd.DataFrame) -> pd.DataFrame:
    bad = df[df.label_huy.isin(["sai", "không rõ"])].assign(code=lambda d: d.note.map(note_code))
    return bad.groupby(["label_huy", "code"]).size().rename("count").reset_index().sort_values("count", ascending=False)


def _jaccard(a: str, b: str) -> float:
    x, y = set(normalize_name(a).split()), set(normalize_name(b).split())
    return len(x & y) / len(x | y) if x | y else 0.0


def make_split(df: pd.DataFrame, few_shot: list[str], seed: int = SEED) -> pd.DataFrame:
    has_rel = df.relations_huy.str.strip().str.upper() != "NONE"
    docs = df.assign(has_relation=has_rel).groupby("document_id").has_relation.any()
    forced = set(df.loc[df.sentence.map(lambda s: max((_jaccard(s, f) for f in few_shot), default=0) >= FEW_SHOT_OVERLAP), "document_id"])
    rng = random.Random(seed)
    dev = set(forced)
    for flag in (True, False):
        group = sorted(d for d, v in docs.items() if v == flag)
        rng.shuffle(group)
        quota = round(len(group) * DEV_SHARE)
        for d in group:
            if sum(docs[x] == flag for x in dev) >= quota:
                break
            dev.add(d)
    return df[["gold_id", "document_id"]].assign(
        has_relation=has_rel.values,
        split=df.document_id.map(lambda d: "dev" if d in dev else "test"),
        reason=df.document_id.map(lambda d: "trùng ví dụ few-shot" if d in forced else ""),
    )


def split(force: bool = False) -> None:
    from .slm import FEW_SHOT

    if SPLIT_FILE.exists() and not force:
        raise SystemExit(f"{SPLIT_FILE} đã có; đổi cách chia sau khi đã chỉnh prompt sẽ làm hỏng tập test. Dùng --force nếu thật sự cần.")
    df = _read(SENTENCES_FILE)
    if errors := check_sentences(df):
        raise SystemExit("Sửa nhãn câu trước khi chia (main.py gold check):\n" + "\n".join(errors))
    out = make_split(df, [s for s, _ in FEW_SHOT])
    out.to_csv(SPLIT_FILE, index=False, encoding="utf-8-sig")
    print(out.groupby(["split", "has_relation"]).size().unstack(fill_value=0).to_string())
    print(f"Ép vào dev: {out.loc[out.reason != '', 'gold_id'].tolist()}")
    print(f"→ {SPLIT_FILE}")


def load_split() -> dict[str, str]:
    if not SPLIT_FILE.exists():
        return {}
    df = _read(SPLIT_FILE)
    return dict(zip(df.gold_id, df.split))


def score() -> None:
    df = _read(RELATIONS_FILE)
    if errors := check_relations(df):
        raise SystemExit("Sửa nhãn trước khi chấm (main.py gold check):\n" + "\n".join(errors))
    population = _read(GRAPH_DIR / "relations.csv").relation_type.value_counts().to_dict()
    table, summary = precision_by_type(df, population)
    errors = error_table(df)
    by_platform = df.groupby("platform").label_huy.value_counts().unstack(fill_value=0)
    table.to_csv(GOLD_DIR / "gold_precision_by_type.csv", index=False, encoding="utf-8-sig")
    errors.to_csv(GOLD_DIR / "gold_error_codes.csv", index=False, encoding="utf-8-sig")
    print(table.to_string(index=False))
    print("\nTheo nguồn:\n" + by_platform.to_string())
    print("\nMã lỗi:\n" + errors.to_string(index=False))
    print("\nTổng hợp:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n→ {GOLD_DIR / 'gold_precision_by_type.csv'}, {GOLD_DIR / 'gold_error_codes.csv'}")
