import os
import random

import numpy as np
import pandas as pd
import requests

from .common import normalize_name
from .gold import GOLD_DIR
from .graph import GRAPH_DIR

OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
DIMENSIONS = 1024
# graph_clean (web pipeline, 11/11) còn alias gộp nhầm trước bản sửa 23/11; dùng đồ thị chính.
ENTITIES = GRAPH_DIR / "entities.csv"
PASS_RATE = 0.9
SEED = 42


def clean(text: str) -> str:
    # Giữ nguyên dấu và hoa/thường: bge-m3 đa ngôn ngữ, bỏ dấu làm mất nghĩa tiếng Việt.
    return " ".join(str(text).split())


def embed(texts: list[str], model: str = EMBED_MODEL, timeout: int = 120) -> np.ndarray:
    r = requests.post(f"{OLLAMA}/api/embed", json={"model": model, "input": [clean(t) for t in texts], "truncate": True}, timeout=timeout)
    r.raise_for_status()
    vectors = np.asarray(r.json()["embeddings"], dtype=np.float32)
    if vectors.shape != (len(texts), DIMENSIONS):
        raise ValueError(f"{model} trả vector {vectors.shape}, cần ({len(texts)}, {DIMENSIONS})")
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def alias_pairs(entities: pd.DataFrame) -> list[tuple[str, str, str]]:
    pairs = []
    for r in entities.itertuples():
        for alias in str(r.aliases).split("|"):
            alias = alias.strip()
            if alias and normalize_name(alias) != normalize_name(r.canonical_name):
                pairs.append((r.entity_id, r.canonical_name, alias))
    return pairs


def check_aliases(n: int = 20, seed: int = SEED) -> pd.DataFrame:
    entities = pd.read_csv(ENTITIES, encoding="utf-8-sig", dtype=str).fillna("")
    pairs = alias_pairs(entities)
    rng = random.Random(seed)
    by_entity: dict[str, tuple[str, str, str]] = {}
    for p in rng.sample(pairs, len(pairs)):
        by_entity.setdefault(p[0], p)
    chosen = list(by_entity.values())[:n]
    canon = [c for _, c, _ in chosen]
    alias = [a for _, _, a in chosen]
    type_of = dict(zip(entities.entity_id, entities.entity_type))
    others = entities[~entities.entity_id.isin({e for e, _, _ in chosen})]
    pool = {t: g.canonical_name.tolist() for t, g in others.groupby("entity_type")}
    negatives = [rng.choice(pool[type_of[e]]) for e, _, _ in chosen]
    v_canon, v_alias, v_neg = embed(canon), embed(alias), embed(negatives)
    sim = v_alias @ v_canon.T
    rows = []
    for i, (entity_id, c, a) in enumerate(chosen):
        rows.append({
            "entity_id": entity_id, "entity_type": type_of[entity_id], "canonical_name": c, "alias": a, "random_name": negatives[i],
            "cos_alias": round(float(sim[i, i]), 4), "cos_random": round(float(v_alias[i] @ v_neg[i]), 4),
            "alias_above_random": bool(sim[i, i] > v_alias[i] @ v_neg[i]),
            "top1_among_sample": bool(sim[i].argmax() == i),
        })
    df = pd.DataFrame(rows)
    out = GOLD_DIR / "embedding_alias_check.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    rate, top1 = df.alias_above_random.mean(), df.top1_among_sample.mean()
    print(df[["entity_type", "canonical_name", "alias", "random_name", "cos_alias", "cos_random", "alias_above_random", "top1_among_sample"]].to_string(index=False))
    print(f"\n{EMBED_MODEL}: {DIMENSIONS} chiều; {len(df)} cặp alias (trong {len(pairs)} cặp khác biệt thật)")
    print(f"cos alias trung vị {df.cos_alias.median():.3f} | cos ngẫu nhiên trung vị {df.cos_random.median():.3f}")
    print(f"alias > ngẫu nhiên: {rate:.0%} | alias tìm đúng tên chuẩn trong {len(df)} tên: {top1:.0%}")
    print(f"{'QUA' if rate >= PASS_RATE else 'CHƯA QUA'} (ngưỡng {PASS_RATE:.0%}); chi tiết: {out}")
    return df
