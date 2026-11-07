import csv
import os
import re
from datetime import datetime
from urllib.parse import quote_plus

import requests
import yt_dlp

from .common import JsonlStore, in_period, log_run, merge_candidates, normalize_name, now_iso, parse_date, polite_sleep, read_seeds, today_iso
from .config import INTERIM_DIR, PERIOD_END, PERIOD_START, RAW_DIR, ROOT, VN_TZ
from .net import QuotaExceeded, get_json
from .scope import SHORT_REASON, Scope

API = "https://www.googleapis.com/youtube/v3"
CHANNEL_FILTER = "EgIQAg%253D%253D"
RAW_YT = RAW_DIR / "youtube"

_YDL_BASE = {"quiet": True, "no_warnings": True, "skip_download": True}


def _period_status(d) -> str:
    if d is None:
        return "unknown"
    if d < PERIOD_START:
        return "before"
    if d > PERIOD_END:
        return "after"
    return "in"


NOT_FOUND = "không tìm thấy kênh tick xanh"
CHANNEL_BLOCKLIST = ROOT / "seeds" / "channel_blocklist.csv"
OK_SUFFIX = {"official", "offical", "officiel", "channel", "music", "band", "tv", "vevo", "chanel", "s"}


def blocked_channels() -> set[str]:
    if not CHANNEL_BLOCKLIST.exists():
        return set()
    with CHANNEL_BLOCKLIST.open(encoding="utf-8-sig", newline="") as f:
        return {r["channel_id"] for r in csv.DictReader(f) if r.get("channel_id")}


def _clean_suffix(target: str, title_norm: str) -> bool:
    """Sau tên nghệ sĩ chỉ được có các từ như Official/Channel/Music; tránh nhận nhầm kiểu 'Orange Juice Gaming'."""
    return all(w in OK_SUFFIX for w in title_norm[len(target):].split())


def resolve(seeds: list[dict], per_seed: int = 6, checkpoint=None, every: int = 10) -> list[dict]:
    """Tìm kênh ứng viên; chỉ tự điền kênh có tick xanh và tên khớp, còn lại để người duyệt."""
    out_rows = []
    done: set[str] = set()
    blocked = blocked_channels()

    def save() -> None:
        merge_candidates(INTERIM_DIR / "youtube_channel_candidates.csv", [r for r in out_rows if r["seed_id"] in done], done)
        if checkpoint:
            checkpoint()

    with yt_dlp.YoutubeDL({**_YDL_BASE, "extract_flat": "in_playlist", "playlistend": per_seed}) as ydl:
        for i, seed in enumerate(seeds, 1):
            url = f"https://www.youtube.com/results?search_query={quote_plus(seed['name'])}&sp={CHANNEL_FILTER}"
            try:
                entries = ydl.extract_info(url, download=False).get("entries") or []
            except Exception as ex:
                log_run("youtube", seed["seed_id"], seed["name"], "resolve_error", message=str(ex))
                continue
            target = normalize_name(seed["name"])
            best = None
            for rank, e in enumerate(entries, 1):
                title = e.get("title") or ""
                norm = normalize_name(title)
                name_match = bool(target) and (norm == target or norm.startswith(target + " "))
                is_topic = title.endswith("- Topic")
                row = {
                    "seed_id": seed["seed_id"],
                    "seed_name": seed["name"],
                    "rank": rank,
                    "channel_id": e.get("channel_id") or e.get("id"),
                    "channel_title": title,
                    "handle": e.get("uploader_id") or "",
                    "verified": e.get("channel_is_verified") is True,
                    "followers": e.get("channel_follower_count") or "",
                    "name_match": name_match,
                    "is_topic": is_topic,
                    "chosen": False,
                    "needs_review": False,
                }
                if row["channel_id"] in blocked:
                    row["name_match"] = False
                elif row["verified"] and name_match and not is_topic and not _clean_suffix(target, norm):
                    row["needs_review"] = True
                if row["verified"] and row["name_match"] and not is_topic and not row["needs_review"]:
                    if best is None or (row["followers"] or 0) > (best["followers"] or 0):
                        best = row
                out_rows.append(row)
            if best:
                best["chosen"] = True
                if not seed.get("youtube_channel_id"):
                    seed["youtube_channel_id"] = best["channel_id"]
                    seed["youtube_channel_name"] = best["channel_title"]
                    seed["youtube_verified"] = "có"
            elif not seed.get("youtube_channel_id"):
                seed["youtube_verified"] = NOT_FOUND
            seed["checked_at"] = today_iso()
            done.add(seed["seed_id"])
            log_run("youtube", seed["seed_id"], seed["name"], "resolved" if best else "no_verified_match", new_items=len(entries))
            print(f"  [{i}/{len(seeds)}] {seed['name']}: {best['channel_title'] if best else '— không có kênh tick xanh khớp tên'}", flush=True)
            if i % every == 0:
                save()
            polite_sleep(1.0, 2.5)

    save()
    return out_rows


def _ytdlp_record(info: dict, seed_id: str) -> dict:
    ts = info.get("timestamp") or info.get("release_timestamp")
    d = datetime.fromtimestamp(ts, VN_TZ).date() if ts else parse_date(info.get("upload_date"))
    return {
        "video_id": info["id"],
        "platform": "youtube",
        "backend": "yt-dlp",
        "seed_id": seed_id,
        "url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={info['id']}",
        "title": info.get("title"),
        "description": info.get("description") or "",
        "published_at": d.isoformat() if d else None,
        "period_status": _period_status(d),
        "channel": info.get("channel"),
        "channel_id": info.get("channel_id"),
        "channel_handle": info.get("uploader_id"),
        "channel_is_verified": info.get("channel_is_verified"),
        "tags": info.get("tags") or [],
        "categories": info.get("categories") or [],
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "music_track": info.get("track"),
        "music_artists": info.get("artists"),
        "music_album": info.get("album"),
        "music_release_date": info.get("release_date"),
        "live_status": info.get("live_status"),
        "collected_at": now_iso(),
    }


def _skip_record(seed_id: str, vid: str, title: str | None, d, reason: str) -> dict:
    """Chỉ lưu ID và lý do để không tải lại, đồng thời đếm được số video bị lọc ở tầng 1."""
    return {
        "video_id": vid,
        "platform": "youtube",
        "seed_id": seed_id,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "title": title,
        "published_at": d.isoformat() if d else None,
        "period_status": _period_status(d),
        "crawl_skip_reason": reason,
        "collected_at": now_iso(),
    }


def crawl_ytdlp(seed: dict, max_videos: int, scope: Scope, stop_after_old: int = 5) -> None:
    cid = seed["youtube_channel_id"]
    store = JsonlStore(RAW_YT / f"{cid}.jsonl", "video_id")
    old_ids = {r["video_id"] for r in store.read() if r.get("period_status") == "before"}
    try:
        with yt_dlp.YoutubeDL({**_YDL_BASE, "extract_flat": "in_playlist", "playlistend": max_videos}) as ydl:
            entries = ydl.extract_info(f"https://www.youtube.com/channel/{cid}/videos", download=False).get("entries") or []
    except Exception as ex:
        log_run("youtube", seed["seed_id"], cid, "list_error", message=str(ex))
        return

    new = skipped = errors = old_streak = filtered = 0
    with yt_dlp.YoutubeDL({**_YDL_BASE, "ignore_no_formats_error": True}) as ydl:
        for e in entries:
            vid = e["id"]
            if vid in store:
                skipped += 1
                old_streak = old_streak + 1 if vid in old_ids else 0
                if old_streak >= stop_after_old:
                    break
                continue
            if scope.is_short(e.get("title"), e.get("duration")):
                store.append(_skip_record(seed["seed_id"], vid, e.get("title"), None, SHORT_REASON))
                filtered += 1
                continue
            try:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
            except Exception as ex:
                errors += 1
                log_run("youtube", seed["seed_id"], vid, "video_error", message=str(ex))
                continue
            rec = _ytdlp_record(info, seed["seed_id"])
            category = "Music" if "Music" in rec["categories"] else None
            reason = scope.crawl_skip_reason(seed["seed_id"], rec["title"], rec["duration"], category) if rec["period_status"] == "in" else None
            if reason:
                store.append(_skip_record(seed["seed_id"], vid, rec["title"], parse_date(rec["published_at"]), reason))
                filtered += 1
            else:
                store.append(rec)
                new += 1
            old_streak = old_streak + 1 if rec["period_status"] == "before" else 0
            if old_streak >= stop_after_old:
                break
            polite_sleep(0.8, 2.0)
    log_run("youtube", seed["seed_id"], cid, "ok" if not errors else "partial", new, skipped, f"errors={errors}; filtered={filtered}; listed={len(entries)}")
    print(f"  {seed['name']}: +{new} video, lọc {filtered}, bỏ qua {skipped}, lỗi {errors}")


def crawl_api(seed: dict, api_key: str, max_videos: int, session: requests.Session, scope: Scope) -> None:
    cid = seed["youtube_channel_id"]
    store = JsonlStore(RAW_YT / f"{cid}.jsonl", "video_id")
    pending: list[str] = []
    page_token = None
    seen = 0
    reached_old = False
    while not reached_old and seen < max_videos:
        params = {"part": "contentDetails", "playlistId": "UU" + cid[2:], "maxResults": 50, "key": api_key}
        if page_token:
            params["pageToken"] = page_token
        data = get_json(session, f"{API}/playlistItems", params=params)
        for item in data.get("items", []):
            seen += 1
            vid = item["contentDetails"]["videoId"]
            d = parse_date(item["contentDetails"].get("videoPublishedAt"))
            if d and d < PERIOD_START:
                reached_old = True
                break
            if vid not in store and (d is None or in_period(d)):
                pending.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    new = filtered = 0
    for i in range(0, len(pending), 50):
        batch = pending[i : i + 50]
        data = get_json(session, f"{API}/videos", params={"part": "snippet,contentDetails,statistics", "id": ",".join(batch), "key": api_key})
        for v in data.get("items", []):
            sn = v["snippet"]
            d = parse_date(sn.get("publishedAt"))
            reason = scope.crawl_skip_reason(seed["seed_id"], sn.get("title"), v.get("contentDetails", {}).get("duration"), sn.get("categoryId"))
            if reason:
                store.append(_skip_record(seed["seed_id"], v["id"], sn.get("title"), d, reason))
                filtered += 1
                continue
            store.append(
                {
                    "video_id": v["id"],
                    "platform": "youtube",
                    "backend": "youtube-data-api-v3",
                    "seed_id": seed["seed_id"],
                    "url": f"https://www.youtube.com/watch?v={v['id']}",
                    "title": sn.get("title"),
                    "description": sn.get("description") or "",
                    "published_at": d.isoformat() if d else None,
                    "period_status": _period_status(d),
                    "channel": sn.get("channelTitle"),
                    "channel_id": sn.get("channelId"),
                    "channel_handle": None,
                    "channel_is_verified": None,
                    "tags": sn.get("tags") or [],
                    "categories": [sn.get("categoryId")],
                    "duration": v.get("contentDetails", {}).get("duration"),
                    "view_count": v.get("statistics", {}).get("viewCount"),
                    "like_count": v.get("statistics", {}).get("likeCount"),
                    "live_status": sn.get("liveBroadcastContent"),
                    "collected_at": now_iso(),
                }
            )
            new += 1
    log_run("youtube", seed["seed_id"], cid, "ok", new, seen - len(pending), f"backend=api; filtered={filtered}")
    print(f"  {seed['name']}: +{new} video, lọc {filtered} (quét {seen})")


CHANNEL_ID = re.compile(r"^UC[0-9A-Za-z_-]{22}$")


def normalize_manual_channels(seeds: list[dict]) -> bool:
    """Đổi link kênh hoặc @handle người dùng dán tay thành channel ID; trả True nếu có thay đổi."""
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    session = requests.Session()
    changed = False
    for s in seeds:
        raw = (s.get("youtube_channel_id") or "").strip()
        if not raw:
            continue
        cid = raw
        if not CHANNEL_ID.match(raw):
            m = re.search(r"/channel/(UC[0-9A-Za-z_-]{22})", raw)
            h = re.search(r"@([A-Za-z0-9._-]+)", raw)
            if m:
                cid = m.group(1)
            elif h and api_key:
                items = get_json(session, f"{API}/channels", params={"part": "snippet", "forHandle": h.group(1), "key": api_key}).get("items") or []
                if not items:
                    print(f"  ⚠ {s['name']}: không tìm thấy kênh cho '{raw}'")
                    continue
                cid = items[0]["id"]
                s["youtube_channel_name"] = items[0]["snippet"]["title"]
            else:
                print(f"  ⚠ {s['name']}: '{raw}' không phải channel ID / link kênh / @handle hợp lệ")
                continue
        if cid != raw or s.get("youtube_verified") in {"", NOT_FOUND}:
            s["youtube_channel_id"] = cid
            if s.get("youtube_verified") in {"", NOT_FOUND, None}:
                s["youtube_verified"] = "thủ công"
            changed = True
    return changed


def crawl(seeds: list[dict], backend: str, max_videos: int) -> None:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if backend == "auto":
        backend = "api" if api_key else "ytdlp"
    if backend == "api" and not api_key:
        raise SystemExit("Thiếu YOUTUBE_API_KEY trong .env")
    targets = [s for s in seeds if s.get("youtube_channel_id")]
    print(f"YouTube ({backend}): {len(targets)}/{len(seeds)} seed đã có kênh")
    session = requests.Session()
    scope = Scope(read_seeds())
    for seed in targets:
        try:
            if backend == "api":
                crawl_api(seed, api_key, max_videos, session, scope)
            else:
                crawl_ytdlp(seed, max_videos, scope)
        except QuotaExceeded as ex:
            log_run("youtube", seed["seed_id"], seed["youtube_channel_id"], "quota_exceeded", message=str(ex))
            print("Hết quota YouTube API hôm nay; chạy lại sau khi quota reset (14:00–15:00 giờ VN).")
            return
        except Exception as ex:
            log_run("youtube", seed["seed_id"], seed["youtube_channel_id"], "error", message=str(ex))
            print(f"  {seed['name']}: lỗi {ex}")
