import csv
import os
import re

import requests

from .common import JsonlStore, log_run, now_iso, parse_date
from .config import RAW_DIR, ROOT
from .net import QuotaExceeded, get_json
from .scope import SHORT_MAX_SECONDS, iso_duration_seconds
from .youtube import _period_status

API = "https://www.googleapis.com/youtube/v3"
SHOWS_PATH = ROOT / "seeds" / "shows.csv"
RAW_SHOWS = RAW_DIR / "youtube_shows"
PLAYLIST_RE = re.compile(r"[?&]list=([A-Za-z0-9_-]+)")


def read_shows() -> list[dict]:
    with SHOWS_PATH.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def playlist_ids(show: dict) -> list[str]:
    return PLAYLIST_RE.findall(show.get("playlist_urls", ""))


def _ytdlp_playlist_ids(pid: str) -> list[str]:
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/playlist?list={pid}", download=False)
    return [e["id"] for e in info.get("entries") or [] if e and e.get("id")]


def crawl_show(show: dict, api_key: str, session: requests.Session) -> None:
    store = JsonlStore(RAW_SHOWS / f"{show['show_id']}.jsonl", "video_id")
    video_playlists: dict[str, list[str]] = {}
    for pid in playlist_ids(show):
        token = None
        while True:
            params = {"part": "contentDetails", "playlistId": pid, "maxResults": 50, "key": api_key}
            if token:
                params["pageToken"] = token
            try:
                data = get_json(session, f"{API}/playlistItems", params=params)
            except requests.HTTPError as ex:
                # API hay trả 404 giữa chừng với playlist rất dài; lấy phần còn lại bằng yt-dlp.
                if ex.response is None or ex.response.status_code != 404 or not token:
                    raise
                for vid in _ytdlp_playlist_ids(pid):
                    video_playlists.setdefault(vid, [])
                    if pid not in video_playlists[vid]:
                        video_playlists[vid].append(pid)
                log_run("youtube_show", show["show_id"], pid, "fallback_ytdlp", message="playlistItems 404 khi phân trang")
                break
            for item in data.get("items", []):
                video_playlists.setdefault(item["contentDetails"]["videoId"], []).append(pid)
            token = data.get("nextPageToken")
            if not token:
                break

    pending = [v for v in video_playlists if v not in store]
    new = filtered = 0
    for i in range(0, len(pending), 50):
        batch = pending[i : i + 50]
        data = get_json(session, f"{API}/videos", params={"part": "snippet,contentDetails,statistics", "id": ",".join(batch), "key": api_key})
        for v in data.get("items", []):
            sn = v["snippet"]
            d = parse_date(sn.get("publishedAt"))
            seconds = iso_duration_seconds(v.get("contentDetails", {}).get("duration"))
            status = _period_status(d)
            skip = None
            if status != "in":
                skip = "ngoài giai đoạn"
            elif seconds is not None and seconds <= SHORT_MAX_SECONDS:
                skip = "video ngắn/Shorts"
            store.append(
                {
                    "video_id": v["id"],
                    "platform": "youtube",
                    "layer": 0,
                    "show_id": show["show_id"],
                    "playlist_ids": video_playlists[v["id"]],
                    "url": f"https://www.youtube.com/watch?v={v['id']}",
                    "title": sn.get("title"),
                    "description": "" if skip else sn.get("description") or "",
                    "published_at": d.isoformat() if d else None,
                    "period_status": status,
                    "crawl_skip_reason": skip,
                    "channel": sn.get("channelTitle"),
                    "channel_id": sn.get("channelId"),
                    "tags": [] if skip else sn.get("tags") or [],
                    "categories": [sn.get("categoryId")],
                    "duration": v.get("contentDetails", {}).get("duration"),
                    "view_count": v.get("statistics", {}).get("viewCount"),
                    "collected_at": now_iso(),
                }
            )
            if skip:
                filtered += 1
            else:
                new += 1
    log_run("youtube_show", show["show_id"], show["show_name"], "ok", new, len(video_playlists) - len(pending), f"filtered={filtered}")
    print(f"  {show['show_id']} {show['show_name']} {show.get('season') or ''} ({show.get('year')}): +{new} video, lọc {filtered}, đã có {len(video_playlists) - len(pending)}")


def crawl(show_ids: list[str] | None) -> None:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Thiếu YOUTUBE_API_KEY trong .env")
    shows = [s for s in read_shows() if not show_ids or s["show_id"] in set(show_ids)]
    session = requests.Session()
    print(f"Tầng 0: {len(shows)} chương trình/sự kiện")
    for show in shows:
        try:
            crawl_show(show, api_key, session)
        except QuotaExceeded as ex:
            log_run("youtube_show", show["show_id"], show["show_name"], "quota_exceeded", message=str(ex))
            print("Hết quota YouTube API hôm nay; chạy lại sau khi quota reset (14:00–15:00 giờ VN).")
            return
        except Exception as ex:
            log_run("youtube_show", show["show_id"], show["show_name"], "error", message=str(ex))
            print(f"  {show['show_id']}: lỗi {ex}")
