import csv
from collections import Counter

from .common import iter_jsonl, now_iso
from .config import INTERIM_DIR, RAW_DIR
from .scope import Scope
from .shows import read_shows

DOCUMENT_COLUMNS = [
    "document_id",
    "url",
    "source_name",
    "source_type",
    "title",
    "published_at",
    "collected_at",
    "content",
    "collection_method",
    "document_status",
    "author",
    "account_verified",
    "exclude_reason",
    "platform",
    "platform_item_id",
    "seed_ids",
    "content_tag",
]
EXCLUDED = "loại bỏ"

_VERIFIED = {True: "có", False: "không", None: "không rõ"}
# Chỉ Bước 5 (làm sạch, lọc phạm vi, chống trùng) mới được đổi sang hợp lệ/trùng lặp/loại bỏ.
PENDING = "cần kiểm tra"


METHOD = {"yt-dlp": "yt-dlp", "youtube-search+api": "Tìm theo tên (yt-dlp) + API", None: "API"}


def _youtube_docs(verified_channels: dict[str, str], seed_ids: set[str], show_ids: set[str]) -> dict[str, dict]:
    docs: dict[str, dict] = {}
    paths = [p for p in sorted((RAW_DIR / "youtube").glob("*.jsonl")) if p.stem in verified_channels]
    paths += [p for p in sorted((RAW_DIR / "youtube_search").glob("*.jsonl")) if p.stem in seed_ids]
    paths += [p for p in sorted((RAW_DIR / "youtube_shows").glob("*.jsonl")) if p.stem in show_ids]
    for r in iter_jsonl(paths):
        if r.get("period_status") != "in" or r.get("crawl_skip_reason"):
            continue
        vid = r["video_id"]
        owner = r.get("seed_id") or r.get("show_id")
        if vid in docs:
            docs[vid]["seed_ids"].add(owner)
            continue
        if r.get("show_id"):
            verified_channels.setdefault(r.get("channel_id"), "có")
        verified = r.get("channel_is_verified")
        account_verified = _VERIFIED.get(verified, "không rõ")
        if verified is None and verified_channels.get(r.get("channel_id")) in {"có", "thủ công"}:
            account_verified = "có"
        description = (r.get("description") or "").strip()
        docs[vid] = {
            "document_id": f"DOC_YT_{vid}",
            "url": r["url"],
            "source_name": r.get("channel") or "",
            "source_type": "Mạng xã hội - YouTube",
            "title": r.get("title") or "",
            "published_at": r.get("published_at") or "",
            "collected_at": r.get("collected_at") or "",
            "content": description,
            "collection_method": METHOD.get(r.get("backend"), "API"),
            "document_status": PENDING,
            "author": "",
            "account_verified": account_verified,
            "exclude_reason": "",
            "platform": "youtube",
            "platform_item_id": vid,
            "seed_ids": {owner},
        }
    return docs


def spotify_content(r: dict) -> str:
    lines = [
        f"Phát hành: {r.get('name')} ({r.get('album_type')})",
        "Nghệ sĩ: " + ", ".join(a["name"] for a in r.get("artists", []) if a.get("name")),
        f"Ngày phát hành: {r.get('release_date') or ''}",
        f"Hãng phát hành (label): {r.get('label') or ''}",
    ]
    for c in r.get("copyrights", []):
        lines.append(f"Bản quyền ({c.get('type')}): {c.get('text')}")
    lines.append("Danh sách bài hát:")
    for t in r.get("tracks", []):
        names = ", ".join(a["name"] for a in t.get("artists", []) if a.get("name"))
        lines.append(f"{t.get('track_number')}. {t.get('name')} — {names}")
    return "\n".join(lines)


def _spotify_docs() -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for r in iter_jsonl(sorted((RAW_DIR / "spotify" / "albums").glob("*.jsonl"))):
        aid = r["album_id"]
        if aid in docs:
            docs[aid]["seed_ids"].add(r["seed_id"])
            continue
        docs[aid] = {
            "document_id": f"DOC_SP_{aid}",
            "url": r.get("url") or f"https://open.spotify.com/album/{aid}",
            "source_name": "Spotify",
            "source_type": "Nền tảng âm nhạc - Spotify",
            "title": r.get("name") or "",
            "published_at": r.get("release_date") or "",
            "collected_at": r.get("collected_at") or "",
            "content": spotify_content(r),
            "collection_method": "API",
            "document_status": PENDING,
            "author": "",
            "account_verified": "",
            "exclude_reason": "",
            "platform": "spotify",
            "platform_item_id": aid,
            "seed_ids": {r["seed_id"]},
        }
    return docs


def build(seeds: list[dict]) -> int:
    verified_channels = {s["youtube_channel_id"]: s.get("youtube_verified", "") for s in seeds if s.get("youtube_channel_id")}
    scope = Scope(seeds)
    show_ids = {s["show_id"] for s in read_shows()}
    youtube_docs = list(_youtube_docs(verified_channels, {s["seed_id"] for s in seeds}, show_ids).values())
    for d in youtube_docs:
        d["content_tag"], d["exclude_reason"] = scope.classify(d["seed_ids"], d["title"], d["content"])
        if d["exclude_reason"]:
            d["document_status"] = EXCLUDED
    spotify_docs = list(_spotify_docs().values())
    for d in spotify_docs:
        d["content_tag"] = "release"
    docs = youtube_docs + spotify_docs

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    path = INTERIM_DIR / "documents.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DOCUMENT_COLUMNS)
        writer.writeheader()
        for d in docs:
            writer.writerow({**d, "seed_ids": "|".join(sorted(d["seed_ids"]))})
    print(f"Đã ghi {len(docs)} tài liệu → {path} ({now_iso()})")
    print("Theo content_tag:", dict(Counter(d["content_tag"] for d in docs)))
    print("Theo trạng thái:", dict(Counter(d["document_status"] for d in docs)))
    print("Lý do loại:", dict(Counter(d["exclude_reason"] for d in docs if d["exclude_reason"])))
    return len(docs)
