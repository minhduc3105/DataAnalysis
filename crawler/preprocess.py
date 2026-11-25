import random
import re
from collections import Counter

import pandas as pd

from .config import INTERIM_DIR
from .gold import ARTICLES, GRAPH_DIR, SEED, _dictionary, _tokens, match_spans

OUT_DIR = INTERIM_DIR / "model_handoff" / "preprocess"
# Cùng ngưỡng với lúc lấy mẫu gold_sentences, để F1 benchmark đại diện cho đúng tập câu được gửi vào SLM.
MIN_LEN, MAX_LEN, MIN_KNOWN = 40, 400, 2
ARTIST_TYPES = {"Person", "Group"}
SECONDS_PER_SENTENCE = 6.7
ABBREVIATIONS = {"tp", "ths", "th.s", "ts", "pgs", "gs", "bs", "q", "p", "st", "mr", "mrs", "ms", "dr", "nxb"}
BOUNDARY = re.compile(r"\n|[.!?…]+[\"”’')\]]*(?=\s)|[.!?](?=[^\W\d_])")
INITIALS = re.compile(r"(?:[A-ZĐ]\.)*[A-ZĐ]")
# Mention từ điển vắt qua dấu câu là ghép nhầm hai tên: "Anh Tú (Nguyễn", "Quang, Nhật".
MENTION_CHARS = re.compile(r"[\w .'’&-]+")


def _is_boundary(text: str, start: int, m: re.Match) -> bool:
    if m.group() == "\n":
        return True
    if not text[m.end():m.end() + 1].isspace():
        # Bài cào về hay dính "quốc tế.Và": chỉ tách khi chữ thường liền chữ hoa, tránh TP.HCM, v.v, Zing.vn.
        return text[m.start() - 1:m.start()].islower() and text[m.end()].isupper()
    rest = text[m.end():].lstrip()
    if rest and rest[0].islower():
        return False
    before = text[start:m.start()].split()
    word = before[-1].lstrip("(\"“‘'") if before else ""
    if m.group()[0] == "." and (word.casefold() in ABBREVIATIONS or INITIALS.fullmatch(word)):
        return False
    if m.group()[0] != "…" and not m.group().startswith(".."):
        return True
    segment = text[start:m.end()]
    # Ba chấm nằm trong lời trích chưa đóng ngoặc kép là ngắt giọng, chưa hết câu.
    return segment.count("“") <= segment.count("”") and segment.count('"') % 2 == 0


STYLIZED_TYPES = {"Person", "Group", "Company"}
# Âm tiết tiếng Việt bỏ dấu ("khang", "thanh") viết thường là từ thường, không phải nghệ danh.
VIET_SYLLABLE = re.compile(r"(ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnpqrstvx])?[aeiouy]{1,3}(ch|ng|nh|[cmnpt])?")


def stylized_lower(entities: pd.DataFrame, vocab: dict) -> frozenset:
    """Nghệ danh cố ý viết thường (tlinh, itsnk, monoX): một chữ, không dấu, ≥ 4 ký tự, có trong từ điển."""
    keys = set()
    for e in entities[entities.entity_type.isin(STYLIZED_TYPES)].itertuples():
        for name in [e.canonical_name, *e.aliases.split(" | ")]:
            name = name.strip()
            if name[:1].islower() and name.isascii() and len(name) >= 4 and re.fullmatch(r"\w+", name):
                key = (name.casefold(),)
                if key in vocab and not VIET_SYLLABLE.fullmatch(key[0]):
                    keys.add(key)
    return frozenset(keys)


def common_words(texts, vocab: dict, keep: frozenset = frozenset()) -> set[str]:
    """Tên một chữ mà trong kho bài viết thường gặp ở dạng chữ thường là từ thường (Trong, Còn, Khoa), không phải nghệ danh."""
    single = {k[0] for k in vocab if len(k) == 1 and k not in keep}
    lower, upper = Counter(), Counter()
    for text in texts:
        for w in re.findall(r"\w+", text):
            f = w.casefold()
            if f in single:
                (lower if w[0].islower() else upper)[f] += 1
    return {w for w in single if lower[w] > 0 and lower[w] >= upper[w]}


def mention_filter(common: set[str]):
    def reject(span: str, key: tuple[str, ...]) -> bool:
        return not MENTION_CHARS.fullmatch(span) or (len(key) == 1 and key[0] in common)
    return reject


def _append(out: list, text: str, start: int, end: int) -> None:
    piece = text[start:end]
    s = start + len(piece) - len(piece.lstrip())
    e = start + len(piece.rstrip())
    if e > s:
        out.append((s, e, text[s:e]))


def split_sentences(text: str) -> list[tuple[int, int, str]]:
    out, start = [], 0
    for m in BOUNDARY.finditer(text):
        if _is_boundary(text, start, m):
            _append(out, text, start, m.end())
            start = m.end()
    _append(out, text, start, len(text))
    return out


def preprocess_document(document_id: str, text: str, vocab: dict, reject=None, allow_lower: frozenset = frozenset()) -> tuple[list[dict], list[dict]]:
    sentences, mentions = [], []
    for i, (s, e, sentence) in enumerate(split_sentences(text), 1):
        sid = f"{document_id}:s{i:04d}"
        hits = match_spans(sentence, vocab, reject, allow_lower)
        known = {hit for _, _, hit in hits}
        sentences.append({
            "document_id": document_id, "sentence_id": sid, "start": s, "end": e, "sentence": sentence,
            "n_known": len(known), "has_artist": any(t in ARTIST_TYPES for _, t in known),
            "is_candidate": MIN_LEN <= len(sentence) <= MAX_LEN and len(known) >= MIN_KNOWN and any(t in ARTIST_TYPES for _, t in known),
        })
        for ms, me, (canonical, etype) in hits:
            mentions.append({
                "mention_id": f"{document_id}:d{len(mentions) + 1:04d}", "document_id": document_id, "sentence_id": sid,
                "start": s + ms, "end": s + me, "text": text[s + ms : s + me], "canonical_name": canonical, "type": etype,
            })
    return sentences, mentions


def check_offsets(texts: dict[str, str], sentences: pd.DataFrame, mentions: pd.DataFrame) -> list[str]:
    errors = [f"{r.sentence_id}: text[start:end] khác sentence" for r in sentences.itertuples() if texts[r.document_id][r.start : r.end] != r.sentence]
    errors += [f"{r.mention_id}: text[start:end] khác mention" for r in mentions.itertuples() if texts[r.document_id][r.start : r.end] != r.text]
    return errors


def run(docs: int | None = None, seed: int = SEED) -> None:
    articles = pd.read_csv(ARTICLES, encoding="utf-8-sig", dtype=str).fillna("")
    articles["text"] = articles.body_text.where(articles.body_text != "", articles.content)
    vocab = _dictionary()
    entities = pd.read_csv(GRAPH_DIR / "entities.csv", encoding="utf-8-sig", dtype=str).fillna("")
    allow_lower = stylized_lower(entities, vocab)
    common = common_words(articles.text, vocab, allow_lower)
    reject = mention_filter(common)
    if docs:
        articles = articles.loc[sorted(random.Random(seed).sample(list(articles.index), docs))]
    sentences, mentions = [], []
    for a in articles.itertuples():
        s, m = preprocess_document(a.document_id, a.text, vocab, reject, allow_lower)
        sentences += s
        mentions += m
    sdf, mdf = pd.DataFrame(sentences), pd.DataFrame(mentions)
    errors = check_offsets(dict(zip(articles.document_id, articles.text)), sdf, mdf)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"sample{docs}" if docs else "all"
    for df, name in [(sdf, f"sentences_{tag}.csv"), (mdf, f"mentions_{tag}.csv")]:
        try:
            df.to_csv(OUT_DIR / name, index=False, encoding="utf-8-sig")
        except PermissionError:
            raise SystemExit(f"Không ghi được {OUT_DIR / name}: file đang mở trong Excel/chương trình khác, đóng lại rồi chạy lại.")
    n_cand = int(sdf.is_candidate.sum())
    print(f"{len(articles)} bài → {len(sdf)} câu, {len(mdf)} mention từ điển, {sdf.sentence.nunique()} câu khác nhau")
    print(f"Bỏ {len(common)} tên một chữ là từ thường: {', '.join(sorted(common))}")
    print(f"Nhận cả dạng viết thường cho {len(allow_lower)} nghệ danh cố ý viết thường: {', '.join(sorted(' '.join(k) for k in allow_lower))}")
    print(f"Vị trí đúng (text[start:end] == câu/mention): {len(sdf) + len(mdf) - len(errors)}/{len(sdf) + len(mdf)}")
    for err in errors[:10]:
        print("  LỖI", err)
    n_unique = sdf[sdf.is_candidate].sentence.nunique()
    print(f"Câu ứng viên gửi SLM ({MIN_LEN}–{MAX_LEN} ký tự, ≥{MIN_KNOWN} thực thể đã biết, có nghệ sĩ): {n_cand} ({n_cand / max(len(sdf), 1):.1%}), {n_unique} câu khác nhau")
    print(f"Ứng viên theo số thực thể đã biết: {sdf[sdf.is_candidate].n_known.clip(upper=5).value_counts().sort_index().to_dict()} (5 = từ 5 trở lên)")
    print(f"Ước tính qwen3:8b ở {SECONDS_PER_SENTENCE} s/câu: {n_unique * SECONDS_PER_SENTENCE / 3600:.1f} giờ (chỉ chạy câu khác nhau)")
    print(f"Đã ghi {OUT_DIR / f'sentences_{tag}.csv'} và mentions_{tag}.csv")
    if errors:
        raise SystemExit(1)
