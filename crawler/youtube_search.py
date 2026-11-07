import os
import re
from urllib.parse import quote_plus

import requests
import yt_dlp

from .common import JsonlStore, log_run, normalize_name, now_iso, parse_date, polite_sleep, read_seeds
from .config import RAW_DIR
from .net import QuotaExceeded, get_json
from .scope import MINOR_VERSION, Scope
from .shows import read_shows
from .youtube import API, _period_status

RAW_SEARCH = RAW_DIR / "youtube_search"
VIDEO_FILTER = "EgIQAQ%253D%253D"


def trusted_channels(seeds: list[dict]) -> set[str]:
    """Kênh show chính thức và kênh nghệ sĩ đã xác minh trong seeds."""
    chans = {c.strip() for s in read_shows() for c in s.get("channel_id", "").split("|") if c.strip()}
    chans |= {s["youtube_channel_id"] for s in seeds if s.get("youtube_channel_id") and s.get("youtube_verified") in {"có", "không rõ", "thủ công"}}
    return chans


def _mentions(name: str, text: str) -> bool:
    """Tên nhiều chữ so theo dạng bỏ dấu; tên một chữ phải khớp nguyên dạng để tránh trùng từ thường."""
    if not text:
        return False
    key = normalize_name(name)
    if len(key.split()) > 1:
        return f" {key} " in f" {normalize_name(text)} "
    return bool(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text))


def _search(ydl, name: str, limit: int) -> list[dict]:
    url = f"https://www.youtube.com/results?search_query={quote_plus(name)}&sp={VIDEO_FILTER}"
    return [e for e in (ydl.extract_info(url, download=False).get("entries") or []) if e and e.get("id") and e.get("duration")]


def search_seed(seed: dict, ydl, api_key: str, session: requests.Session, trusted: set[str], scope: Scope, limit: int) -> None:
    names = [seed["name"]] + [a for a in (seed.get("aliases") or "").split(" | ") if a]
    store = JsonlStore(RAW_SEARCH / f"{seed['seed_id']}.jsonl", "video_id")
    hits: dict[str, dict] = {}
    for e in _search(ydl, seed["name"], limit):
        text = f"{e.get('title') or ''}\n{e.get('description') or ''}"
        if e["id"] in store or not any(_mentions(n, text) for n in names):
            continue
        hits[e["id"]] = e

    new = rejected = 0
    ids = list(hits)
    for i in range(0, len(ids), 50):
        data = get_json(session, f"{API}/videos", params={"part": "snippet,contentDetails,statistics", "id": ",".join(ids[i : i + 50]), "key": api_key})
        for v in data.get("items", []):
            sn = v["snippet"]
            e = hits[v["id"]]
            trust = "kênh có tick xanh" if e.get("channel_is_verified") else ("kênh đã xác minh trong seeds/shows" if sn.get("channelId") in trusted else "")
            d = parse_date(sn.get("publishedAt"))
            text = f"{sn.get('title') or ''}\n{sn.get('description') or ''}"
            reason = None
            if not trust:
                reason = "kênh không xác minh"
            elif _period_status(d) != "in":
                reason = "ngoài giai đoạn"
            elif scope.is_short(sn.get("title"), v.get("contentDetails", {}).get("duration")):
                reason = "video ngắn/Shorts"
            elif MINOR_VERSION.search(sn.get("title") or ""):
                reason = "phiên bản phụ: karaoke/beat"
            elif not any(_mentions(n, text) for n in names):
                reason = "không nhắc tên trong tiêu đề/mô tả"
            if reason:
                rejected += 1
                continue
            store.append(
                {
                    "video_id": v["id"],
                    "platform": "youtube",
                    "backend": "youtube-search+api",
                    "seed_id": seed["seed_id"],
                    "url": f"https://www.youtube.com/watch?v={v['id']}",
                    "title": sn.get("title"),
                    "description": sn.get("description") or "",
                    "published_at": d.isoformat() if d else None,
                    "period_status": "in",
                    "channel": sn.get("channelTitle"),
                    "channel_id": sn.get("channelId"),
                    "channel_is_verified": True if e.get("channel_is_verified") else None,
                    "trust_reason": trust,
                    "tags": sn.get("tags") or [],
                    "categories": [sn.get("categoryId")],
                    "duration": v.get("contentDetails", {}).get("duration"),
                    "view_count": v.get("statistics", {}).get("viewCount"),
                    "collected_at": now_iso(),
                }
            )
            new += 1
    # Ghi dấu đã tìm để lần sau bỏ qua seed này.
    store.append({"video_id": "_searched", "seed_id": seed["seed_id"], "collected_at": now_iso(), "kept": new, "rejected": rejected})
    log_run("youtube_search", seed["seed_id"], seed["name"], "ok", new, rejected, f"hits={len(hits)}")
    print(f"  {seed['name']}: giữ {new} video từ kênh tin cậy, loại {rejected}", flush=True)


def run(seed_ids: list[str] | None, limit: int, force: bool, only_missing: bool) -> None:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Thiếu YOUTUBE_API_KEY trong .env")
    seeds = read_seeds()
    targets = [s for s in seeds if s["entity_type"] in {"Person", "Group"}]
    if seed_ids:
        targets = [s for s in targets if s["seed_id"] in set(seed_ids)]
    elif only_missing:
        targets = [s for s in targets if not s.get("youtube_channel_id")]
    if not force:
        targets = [s for s in targets if "_searched" not in JsonlStore(RAW_SEARCH / f"{s['seed_id']}.jsonl", "video_id")]
    trusted = trusted_channels(seeds)
    scope = Scope(seeds)
    session = requests.Session()
    print(f"Tìm video theo tên cho {len(targets)} người/nhóm (kênh tin cậy: {len(trusted)} + mọi kênh có tick xanh)")
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "playlistend": limit}) as ydl:
        for i, seed in enumerate(targets, 1):
            print(f"[{i}/{len(targets)}]", end=" ", flush=True)
            try:
                search_seed(seed, ydl, api_key, session, trusted, scope, limit)
            except QuotaExceeded as ex:
                log_run("youtube_search", seed["seed_id"], seed["name"], "quota_exceeded", message=str(ex))
                print("Hết quota YouTube API hôm nay; chạy lại sau khi quota reset (14:00–15:00 giờ VN).")
                return
            except Exception as ex:
                log_run("youtube_search", seed["seed_id"], seed["name"], "error", message=str(ex))
                print(f"  {seed['name']}: lỗi {ex}", flush=True)
            polite_sleep(1.0, 2.5)
