import csv
import os
import re
import unicodedata
from collections import defaultdict

from .common import iter_jsonl, normalize_name, read_seeds
from .config import INTERIM_DIR
from .layer1 import (
    CANDIDATES_PATH,
    HANDLE,
    ORG_CHANNEL,
    SHOW_WORDS,
    _blocklist,
    _clean,
    _key,
    _load_cache,
    _songs,
    description_mentions,
    parse_title,
    resolve_handles,
)
from .shows import RAW_SHOWS, read_shows

SONGS_PATH = INTERIM_DIR / "layer1_songs.csv"
ORGS_PATH = INTERIM_DIR / "layer1_orgs.csv"

# Tên miền lnk.to là trang phát hành audio của hãng; tên đầy đủ suy từ tên miền nên vẫn cần duyệt.
LNK_LABELS = {
    "wmvn": "Warner Music Vietnam",
    "umvn": "Universal Music Vietnam",
    "smevn": "Sony Music Entertainment Vietnam",
    "1label": "1Label",
    "mmusicrecords": "M Music Records",
}
LNK = re.compile(r"https?://([A-Za-z0-9]+)\.lnk\.to", re.IGNORECASE)
ORG_NAME = r"([A-ZĐ0-9][\w&.,'’ -]{1,80})"
ORG_PATTERNS = [
    ("Company", "rights_owner", re.compile(r"(?:©|bản quyền)[^\n]*?(?:thuộc về|thuộc bản quyền của|bản quyền của|copyright by|belongs to)\s+" + ORG_NAME, re.IGNORECASE)),
    ("Company", "format_owner", re.compile(r"sản xuất bởi\s+" + ORG_NAME, re.IGNORECASE)),
    ("Company", "format_distributor", re.compile(r"phân phối bởi\s+" + ORG_NAME, re.IGNORECASE)),
    ("Company", "rights_buyer", re.compile(r"được\s+([A-ZĐ][\w&.' ]{1,40}?)\s+mua bản quyền")),
    ("Company", "broadcaster", re.compile(r"(Công [Tt]y (?:Cổ [Pp]hần|TNHH)\s+[\w&.' ]{2,40})")),
    ("Brand", "sponsor", re.compile(r"([A-ZĐ][\w&.'’ ]{1,30}?)\s+đồng hành (?:cùng|với)\s+chương trình")),
    ("Brand", "sponsor", re.compile(r"(?i:nhà tài trợ|đồng hành)(?i: chính thức| kim cương| vàng| bạc| độc quyền)?\s*[:\-–]?\s*([A-ZĐ][\w&.'’]{1,30}(?: [A-ZĐ][\w&.'’]{1,30}){0,3})")),
]
ORG_STOP = re.compile(r"\s*(?:\(|☞|vui lòng|do not|please|\.\s|\.(?=[A-ZĐÀ-Ỹ])|\s-\s)", re.IGNORECASE)
ORG_GENERIC = {"chuong trinh", "video", "kenh", "ban quyen"}


def _org_names(raw: str) -> list[str]:
    raw = re.sub(r"\bCo\.?\s*,?\s*Ltd\b", "Co Ltd", raw, flags=re.IGNORECASE)
    raw = ORG_STOP.split(raw, maxsplit=1)[0].rstrip(" .")
    out = []
    for piece in re.split(r"\s*(?:,|&|\bvà\b|\band\b)\s*", raw):
        piece = piece.strip(" .:;-–\"'“”")
        if 2 <= len(piece) <= 60 and piece[0].isupper() and normalize_name(piece) not in ORG_GENERIC:
            out.append(piece)
    return out


def org_mentions(desc: str) -> list[tuple[str, str, str, str]]:
    """Trả [(tên, Company/Brand, vai trò, câu bằng chứng)] từ mô tả video."""
    found = []
    for line in unicodedata.normalize("NFC", desc or "").splitlines():
        if re.search(r"liên hệ|hotline|email|\bLH\b", line, re.IGNORECASE) and not re.search(r"Công [Tt]y", line):
            continue
        for org_type, role, pat in ORG_PATTERNS:
            for m in pat.finditer(line):
                found += [(n, org_type, role, line.strip()[:200]) for n in _org_names(m.group(1))]
        for sub in LNK.findall(line):
            found.append((LNK_LABELS.get(sub.lower(), f"{sub} (lnk.to)"), "Company", "audio_distributor", line.strip()[:200]))
    return found


def _org_key(name: str) -> str:
    key = normalize_name(name)
    key = re.sub(r"^cong ty(?: co phan| tnhh)?\s+", "", key)
    key = re.sub(r"\bent\b", "entertainment", key)
    key = re.sub(r"(\s+(jsc|company|co ltd|co|ltd|corp))+$", "", key)
    return key.replace(" ", "")


def extract() -> None:
    shows = {s["show_id"]: s for s in read_shows()}
    show_channels = {c.strip() for s in shows.values() for c in s.get("channel_id", "").split("|")}
    seeds = {normalize_name(s["name"]): s for s in read_seeds() if s["entity_type"] in {"Person", "Group"}}
    blocked = _blocklist()

    people: dict[str, dict] = defaultdict(lambda: {"names": defaultdict(int), "roles": set(), "sources": set(), "videos": set(), "shows": set(), "handles": set()})
    songs: dict[str, dict] = defaultdict(lambda: {"names": defaultdict(int), "performers": defaultdict(int), "composers": set(), "producers": set(), "videos": set(), "shows": set(), "mashup": False})
    orgs: dict[str, dict] = defaultdict(lambda: {"names": defaultdict(int), "types": set(), "roles": set(), "videos": set(), "shows": set(), "quotes": []})
    handle_videos: dict[str, set] = defaultdict(set)

    for path in sorted(RAW_SHOWS.glob("*.jsonl")):
        for r in iter_jsonl([path]):
            if r.get("crawl_skip_reason"):
                continue
            vid, sid = r["video_id"], r["show_id"]
            order = shows.get(sid, {}).get("title_order") or "song-artist"
            title_people, title_songs, mashup = parse_title(r.get("title", ""), order)
            credits = description_mentions(r.get("description", ""))
            if order == "free" and any(role == "performer" for _, role in credits):
                segs = [s.strip() for s in _clean(r.get("title", "")).split("|") if s.strip()]
                title_songs, mashup = _songs(segs[0]) if segs else ([], False)

            for name, role, source in [(n, ro, "title") for n, ro in title_people] + [(n, ro, "credit") for n, ro in credits]:
                c = people[_key(name)]
                c["names"][name] += 1
                c["roles"].add(role)
                c["sources"].add(source)
                c["videos"].add(vid)
                c["shows"].add(sid)

            performers = [n for n, ro in title_people + credits if ro == "performer"]
            for song in title_songs:
                s = songs[normalize_name(song)]
                s["names"][song] += 1
                s["videos"].add(vid)
                s["shows"].add(sid)
                s["mashup"] |= mashup
                for n in performers:
                    s["performers"][n] += 1
                if len(title_songs) == 1:
                    s["composers"].update(n for n, ro in credits if ro == "composer")
                    s["producers"].update(n for n, ro in credits if ro == "producer")

            for name, org_type, role, quote in org_mentions(r.get("description", "")):
                o = orgs[_org_key(name)]
                o["names"][name] += 1
                o["types"].add(org_type)
                o["roles"].add(role)
                o["videos"].add(vid)
                o["shows"].add(sid)
                if len(o["quotes"]) < 2 and quote not in o["quotes"]:
                    o["quotes"].append(quote)

            for h in HANDLE.findall(r.get("description", "")):
                handle_videos[h].add((vid, sid))

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    handle_info = resolve_handles(set(handle_videos), api_key) if api_key and handle_videos else _load_cache()
    for h, vids in handle_videos.items():
        info = handle_info.get(h.lower())
        if not info or info["channel_id"] in show_channels:
            continue
        norm = normalize_name(info["title"])
        if ORG_CHANNEL.search(norm) or SHOW_WORDS.search(info["title"]) or re.search(r"\bfans?\b|\bidol\b", norm):
            continue
        c = people[_key(info["title"])]
        c["names"][info["title"]] += 0
        c["handles"].add(f"@{h}|{info['channel_id']}|{info.get('subscribers') or ''}")
        c["sources"].add("handle")
        for vid, sid in vids:
            c["videos"].add(vid)
            c["shows"].add(sid)

    _write_people(people, seeds, blocked)
    _write_songs(songs, blocked)
    _write_orgs(orgs, blocked)


def _top(counter: dict) -> str:
    return max(counter.items(), key=lambda kv: kv[1])[0]


def _write_people(people: dict, seeds: dict, blocked: set) -> None:
    rows = []
    for key, c in people.items():
        if not key or key in blocked:
            continue
        seed = seeds.get(key)
        handle = sorted(c["handles"])[0].split("|") if c["handles"] else ["", "", ""]
        rows.append(
            {
                "candidate_key": key,
                "name": _top(c["names"]),
                "name_variants": " | ".join(sorted(c["names"])),
                "entity_type": "Person",
                "n_videos": len(c["videos"]),
                "n_shows": len(c["shows"]),
                "shows": " ".join(sorted(c["shows"])),
                "roles": " ".join(sorted(c["roles"])),
                "sources": " ".join(sorted(c["sources"])),
                "youtube_handle": handle[0],
                "youtube_channel_id": handle[1] or (seed or {}).get("youtube_channel_id", ""),
                "subscribers": handle[2],
                "in_old_seeds": seed["seed_id"] if seed else "",
                "example_videos": " ".join(f"https://youtu.be/{v}" for v in sorted(c["videos"])[:3]),
                "suggest": "nhận" if len(c["videos"]) >= 2 or c["handles"] or seed else "xem lại",
                "approve": "",
                "review_note": "",
            }
        )
    rows.sort(key=lambda r: (-r["n_shows"], -r["n_videos"], r["name"]))
    _write_preserving_review(CANDIDATES_PATH, rows, key="candidate_key", keep=("entity_type", "approve", "review_note"))
    print(f"Người (Person/Group): {len(rows)} → {CANDIDATES_PATH.name}")
    print(f"  ≥2 video: {sum(r['n_videos'] >= 2 for r in rows)} | ≥2 chương trình: {sum(r['n_shows'] >= 2 for r in rows)} | có kênh YouTube: {sum(bool(r['youtube_channel_id']) for r in rows)}")


def _write_songs(songs: dict, blocked: set) -> None:
    rows = []
    for key, s in songs.items():
        if not key or key in blocked:
            continue
        merged: dict[str, tuple[str, int]] = {}
        for n, cnt in s["performers"].items():
            k = _key(n)
            prev = merged.get(k)
            merged[k] = (prev[0] if prev and prev[1] >= cnt else n, (prev[1] if prev else 0) + cnt)
        perf = sorted(merged.values(), key=lambda kv: -kv[1])
        rows.append(
            {
                "song_key": key,
                "name": _top(s["names"]),
                "name_variants": " | ".join(sorted(s["names"])),
                "performers": " | ".join(n for n, _ in perf[:10]),
                "composers": " | ".join(sorted(s["composers"])),
                "producers": " | ".join(sorted(s["producers"])),
                "n_videos": len(s["videos"]),
                "n_shows": len(s["shows"]),
                "shows": " ".join(sorted(s["shows"])),
                "in_mashup": "có" if s["mashup"] else "",
                "example_videos": " ".join(f"https://youtu.be/{v}" for v in sorted(s["videos"])[:3]),
                "approve": "",
                "review_note": "",
            }
        )
    rows.sort(key=lambda r: (-r["n_videos"], r["name"]))
    _write_preserving_review(SONGS_PATH, rows, key="song_key")
    print(f"Bài hát (Song): {len(rows)} → {SONGS_PATH.name}")
    print(f"  có người trình bày: {sum(bool(r['performers']) for r in rows)} | có nhạc sĩ: {sum(bool(r['composers']) for r in rows)} | nằm trong mashup: {sum(bool(r['in_mashup']) for r in rows)}")


def _write_orgs(orgs: dict, blocked: set) -> None:
    rows = []
    for key, o in orgs.items():
        if not key or key in blocked:
            continue
        rows.append(
            {
                "org_key": key,
                "name": _top(o["names"]),
                "name_variants": " | ".join(sorted(o["names"])),
                "entity_type": "Brand" if o["types"] == {"Brand"} else "Company",
                "roles": " ".join(sorted(o["roles"])),
                "n_videos": len(o["videos"]),
                "n_shows": len(o["shows"]),
                "shows": " ".join(sorted(o["shows"])),
                "evidence": " || ".join(o["quotes"]),
                "example_videos": " ".join(f"https://youtu.be/{v}" for v in sorted(o["videos"])[:3]),
                "approve": "",
                "review_note": "",
            }
        )
    rows.sort(key=lambda r: (r["entity_type"], -r["n_shows"], -r["n_videos"]))
    _write_preserving_review(ORGS_PATH, rows, key="org_key", keep=("entity_type", "approve", "review_note"))
    print(f"Tổ chức (Company/Brand): {len(rows)} → {ORGS_PATH.name}")
    print(f"  Company: {sum(r['entity_type'] == 'Company' for r in rows)} | Brand: {sum(r['entity_type'] == 'Brand' for r in rows)}")


def _write_preserving_review(path, rows: list[dict], key: str, keep=("approve", "review_note")) -> None:
    """Giữ các cột người dùng đã điền (approve, review_note, entity_type) khi chạy lại."""
    if not rows:
        return
    old = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            old = {r[key]: r for r in csv.DictReader(f) if key in r}
    for r in rows:
        prev = old.get(r[key])
        if prev:
            for col in keep:
                if prev.get(col):
                    r[col] = prev[col]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
