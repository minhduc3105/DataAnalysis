import csv
import json
import os
import re
import unicodedata
from collections import defaultdict

import requests

from .common import iter_jsonl, normalize_name, read_seeds
from .config import INTERIM_DIR, ROOT
from .net import QuotaExceeded, get_json
from .shows import RAW_SHOWS, read_shows

API = "https://www.googleapis.com/youtube/v3"
CANDIDATES_PATH = INTERIM_DIR / "layer1_candidates.csv"
HANDLE_CACHE = INTERIM_DIR / "handle_cache.json"

BRACKETS = re.compile(r"\[[^\]]*\]|【[^】]*】|《[^》]*》|\((?:[^)]*(?:official|mv|lyric|audio|visual|live|performance|ver)[^)]*)\)", re.IGNORECASE)
DASH = re.compile(r"\s+[-–—]\s*|\s*[-–—]\s+")
NAME_SPLIT = re.compile(r"\s*(?:,|&|\+|/|\bft\.?|\bfeat\.?|\bfeaturing\b|\s[xX×]\s|\bvà\b|\bwith\b)\s*")
TEAM = re.compile(r"^team\s+(.+)$", re.IGNORECASE)
HANDLE = re.compile(r"(?<![\w.])@([A-Za-z0-9][A-Za-z0-9._-]{2,29})")

CREDIT_ROLES = [
    ("performer", r"trình bày|thể hiện|ca sĩ|performed by|performer|vocals?|giọng ca"),
    ("composer", r"sáng tác(?: mới)?|nhạc sĩ|composer|songwriters?|song writers?|lyricists?|tác giả|lời(?: và nhạc)?|nhạc và lời"),
    ("producer", r"music producers?|producers?|prod(?:uced)?(?: by)?|hòa âm(?: phối khí)?|phối khí|arrangers?|arrangement|beatmaker|beat"),
]
CREDIT_LINE = re.compile(
    r"^\s*[✪★☆►▶•\-–*]*\s*(" + "|".join(p for _, p in CREDIT_ROLES) + r")\s*[:：\-–]?\s+(.{2,200})$",
    re.IGNORECASE | re.MULTILINE,
)

NOT_A_NAME = re.compile(
    r"^(mashup|medley|remix|live|performance|stage|lyrics?|mv|audio|official|concert|tập|episode|team|top ?\d*|cover|ver(?:sion)?|"
    r"acoustic|vòng|công diễn|chung kết|bán kết|ost|ban(?: nhạc)?|đội|nhóm|các anh tài|anh tài|chị đẹp|tân binh|full|karaoke|teaser|trailer)$",
    re.IGNORECASE,
)
SHOW_WORDS = re.compile(
    r"mv lyrics|audio lyrics|live stage|livestage|performance|lsxma|\blsx\b|xhtdrlx|king of rap|top ?40|rap việt|anh trai|say hi|"
    r"chông gai|chị đẹp|tân binh|our song|vietnam idol|masked singer|ca sĩ mặt nạ|biển của hy vọng|hương mùa hè|làn sóng xanh|"
    r"sóng 2\d|tập \d+|concert|xuân hạ thu đông|đạp gió",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = "".join(c for c in text if unicodedata.category(c)[0] != "S" or c in "&+/|")
    return re.sub(r"\s+", " ", BRACKETS.sub(" ", text)).strip(" -–|")


def _capitalized_prefix(name: str) -> str:
    """Giữ phần đầu viết hoa của chuỗi; tên nghệ sĩ trong tiêu đề luôn viết hoa chữ đầu."""
    kept = []
    for tok in name.split():
        if tok[0].isalpha() and tok[0].islower():
            break
        kept.append(tok)
    return " ".join(kept)


TITLE_PREFIX = re.compile(r"^(?:anh tài|chị đẹp|em xinh|tân binh|nsưt|nsnd|ca sĩ|rapper|nhạc sĩ|nhóm|ban nhạc|thí sinh|hlv|giám khảo)\s+", re.IGNORECASE)


def _names(part: str) -> list[str]:
    out = []
    for raw in NAME_SPLIT.split(part or ""):
        raw = re.split(r"[(\[]", raw)[0]
        raw = TITLE_PREFIX.sub("", raw.strip(" .:;-–\"'“”‘’"))
        name = _capitalized_prefix(raw.strip(" .:;-–\"'“”‘’"))
        if 2 <= len(name) <= 40 and not NOT_A_NAME.match(name) and not SHOW_WORDS.search(name) and not name.isdigit():
            out.append(name)
    return out


def title_mentions(title: str, order: str) -> list[tuple[str, str]]:
    """Trả [(tên, vai trò)] rút từ tiêu đề theo kiểu sắp xếp của show."""
    return parse_title(title, order)[0]


MASHUP_WORD = re.compile(r"^(?:mashup|medley|liên khúc|lk)\s*[:\-–]?\s*", re.IGNORECASE)
NOT_SONG = re.compile(r"^(?:tập|episode|ep\.?)\s*\d+|^(?:mv lyrics|audio lyrics|performance|live stage|livestage|highlight|teaser|trailer|full)$", re.IGNORECASE)


def _songs(part: str) -> tuple[list[str], bool]:
    part = part.strip(" .:;\"'“”‘’")
    is_mashup = bool(MASHUP_WORD.match(part)) or bool(re.search(r"\s[xX×]\s", part))
    part = MASHUP_WORD.sub("", part)
    pieces = re.split(r"\s+[xX×+]\s+|\s*,\s*" if is_mashup else r"\s+[xX×+]\s+", part)
    songs = []
    for p in pieces:
        p = re.split(r"[(\[]", p)[0].strip(" .:;-–\"'“”‘’")
        if 1 <= len(p) <= 80 and not NOT_SONG.search(p) and not p.isdigit():
            songs.append(p)
    return songs, is_mashup


def parse_title(title: str, order: str) -> tuple[list[tuple[str, str]], list[str], bool]:
    """Trả (người [(tên, vai trò)], tên bài, có phải mashup) rút từ tiêu đề theo kiểu sắp xếp của show."""
    if order in {"free", "mascot"}:
        return [], [], False
    raw_segments = [s.strip() for s in _clean(title).split("|") if s.strip()]
    if order == "artist|song":
        # Dạng "NGHỆ SĨ | BÀI | tên sự kiện": đoạn đầu luôn là nghệ sĩ, kể cả khi có chữ LSX.
        people = [(n, "performer") for n in _names(raw_segments[0])] if raw_segments else []
        song_seg = next((s for s in raw_segments[1:] if not SHOW_WORDS.search(s)), "")
        songs, mashup = _songs(song_seg) if song_seg and people else ([], False)
        return people, songs, mashup
    segments = [s for s in raw_segments if not (SHOW_WORDS.search(s) and not DASH.search(s))]
    if not segments:
        return [], [], False
    for seg in segments:
        parts = [p for p in DASH.split(seg) if p.strip()]
        if len(parts) < 2:
            continue
        artist_part, song_part = (parts[0], parts[1]) if order == "artist-song" else (parts[1], parts[0])
        people = [(n, "performer") for n in _names(artist_part)]
        for extra in parts[2:]:
            m = TEAM.match(extra.strip())
            if m:
                people += [(n, "coach") for n in _names(m.group(1))]
        if not any(r == "performer" for _, r in people):
            return people, [], False
        songs, mashup = _songs(song_part)
        return people, songs, mashup
    return [], [], False


def description_mentions(desc: str) -> list[tuple[str, str]]:
    found = []
    for m in CREDIT_LINE.finditer(unicodedata.normalize("NFC", desc or "")):
        label, value = m.group(1).lower(), m.group(2)
        role = next(r for r, p in CREDIT_ROLES if re.fullmatch(p, label, re.IGNORECASE))
        value = re.sub(r"\(.*?\)", " ", value)
        for piece in DASH.split(value):
            found += [(n, role) for n in _names(piece)]
    return found


def _load_cache() -> dict:
    if HANDLE_CACHE.exists():
        return json.loads(HANDLE_CACHE.read_text(encoding="utf-8"))
    return {}


def resolve_handles(handles: set[str], api_key: str) -> dict:
    cache = _load_cache()
    session = requests.Session()
    todo = sorted(h for h in handles if h.lower() not in cache)
    try:
        for h in todo:
            data = get_json(session, f"{API}/channels", params={"part": "snippet,statistics", "forHandle": h, "key": api_key})
            items = data.get("items") or []
            cache[h.lower()] = (
                {"channel_id": items[0]["id"], "title": items[0]["snippet"]["title"].strip(), "subscribers": items[0]["statistics"].get("subscriberCount")}
                if items
                else None
            )
    except QuotaExceeded:
        print("Hết quota khi tra @handle; phần còn lại sẽ tra ở lần chạy sau.")
    HANDLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    HANDLE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache


BLOCKLIST_PATH = ROOT / "seeds" / "layer1_blocklist.txt"
ORG_CHANNEL = re.compile(
    r"\b(vie|vtv|htv|yeah1|dong tay|promotion|entertainment|media|studios?|channel|network|giai tri|news|buzz|shows?|talents|production|records?|label)\b"
)


def _blocklist() -> set[str]:
    if not BLOCKLIST_PATH.exists():
        return set()
    lines = BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines()
    return {_key(line) for line in lines if line.strip() and not line.lstrip().startswith("#")}


def _key(name: str) -> str:
    key = normalize_name(name)
    return re.sub(r"\s+(official|music|channel|tv|offical)$", "", key)


