import base64
import os
import re
import time
from datetime import datetime, timedelta

import requests

from .common import JsonlStore, iter_jsonl, log_run, merge_candidates, normalize_name, now_iso, polite_sleep, release_in_period, today_iso
from .config import INTERIM_DIR, RAW_DIR, VN_TZ
from .net import QuotaExceeded, RateLimited, get_json

API = "https://api.spotify.com/v1"
RAW_SP = RAW_DIR / "spotify"
INCLUDE_GROUPS = "album,single,appears_on,compilation"
VERSION_WORDS = re.compile(r"remix|lofi|lo-fi|speed ?up|sped ?up|slowed|acoustic|version|ver\.|beat|instrumental|live|karaoke|edm|vinahouse|mix\b", re.IGNORECASE)
BRACKETS = re.compile(r"\s*[\(\[\{].*?[\)\]\}]")
SHOW_RELEASE = re.compile(r"\btập\s*\d|\bmùa\s*\d|\bepisode\b|\bconcert\b|\blive (?:at|in|session)\b", re.IGNORECASE)


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str, market: str = "VN"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.market = market
        self.session = requests.Session()
        self._token = None
        self._expires = 0.0
        self.calls = 0
        self.top_tracks_ok = True

    @classmethod
    def from_env(cls) -> "SpotifyClient":
        cid = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        if not cid or not secret:
            raise SystemExit("Thiếu SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET trong .env")
        return cls(cid, secret)

    def _auth(self) -> dict:
        if not self._token or time.time() > self._expires - 60:
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            resp = self.session.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {basic}"},
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            self._token = body["access_token"]
            self._expires = time.time() + body.get("expires_in", 3600)
        return {"Authorization": f"Bearer {self._token}"}

    def get(self, path_or_url: str, params: dict | None = None) -> dict:
        url = path_or_url if path_or_url.startswith("http") else f"{API}{path_or_url}"
        data = get_json(self.session, url, params=params, headers=self._auth())
        self.calls += 1
        # Gọi dồn ~4 lần/giây từng làm app Development bị khóa 24 giờ.
        polite_sleep(0.9, 1.5)
        return data

    def paged(self, path: str, params: dict, limit: int):
        """Spotify từng hạ giới hạn `limit` cho app mới; gặp lỗi 400 thì tự giảm xuống 10."""
        try:
            page = self.get(path, {**params, "limit": limit})
        except requests.HTTPError as ex:
            if ex.response is None or ex.response.status_code != 400 or limit <= 10:
                raise
            page = self.get(path, {**params, "limit": 10})
        while page:
            yield from page.get("items", [])
            page = self.get(page["next"]) if page.get("next") else None


def resolve(client: SpotifyClient, seeds: list[dict], per_seed: int = 5) -> list[dict]:
    rows = []
    for seed in seeds:
        try:
            items = client.get("/search", {"q": seed["name"], "type": "artist", "market": client.market, "limit": per_seed})["artists"]["items"]
        except Exception as ex:
            log_run("spotify", seed["seed_id"], seed["name"], "resolve_error", message=str(ex))
            continue
        target = normalize_name(seed["name"])
        exact = [a for a in items if normalize_name(a["name"]) == target]
        chosen = exact[0]["id"] if len(exact) == 1 else None
        for rank, a in enumerate(items, 1):
            rows.append(
                {
                    "seed_id": seed["seed_id"],
                    "seed_name": seed["name"],
                    "rank": rank,
                    "artist_id": a["id"],
                    "artist_name": a["name"],
                    "followers": (a.get("followers") or {}).get("total", ""),
                    "popularity": a.get("popularity", ""),
                    "genres": "|".join(a.get("genres") or []),
                    "url": a.get("external_urls", {}).get("spotify", ""),
                    "exact_name": a in exact,
                    "chosen": a["id"] == chosen,
                }
            )
        if chosen and not seed.get("spotify_artist_id"):
            seed["spotify_artist_id"] = chosen
            seed["spotify_name"] = exact[0]["name"]
            seed["checked_at"] = today_iso()
        status = "resolved" if chosen else ("ambiguous" if len(exact) > 1 else "no_exact_match")
        log_run("spotify", seed["seed_id"], seed["name"], status, new_items=len(items))

    merge_candidates(INTERIM_DIR / "spotify_artist_candidates.csv", rows, {s["seed_id"] for s in seeds})
    return rows


def _artists(objs: list[dict]) -> list[dict]:
    return [{"id": a.get("id"), "name": a.get("name")} for a in objs or []]


def _base_title(name: str) -> str:
    name = BRACKETS.sub("", name or "")
    name = re.split(r"\s+[-–|]\s+|\s+(?:ft|feat)\.?\s+", name, maxsplit=1, flags=re.IGNORECASE)[0]
    return normalize_name(name)


def youtube_views(channel_id: str, artist_name: str = "") -> list[tuple[str, int]]:
    path = RAW_DIR / "youtube" / f"{channel_id}.jsonl"
    if not channel_id or not path.exists():
        return []
    artist = normalize_name(artist_name)
    out = []
    for v in iter_jsonl([path]):
        if v.get("title") and v.get("view_count"):
            # Bỏ tên nghệ sĩ khỏi tiêu đề, nếu không album trùng tên nghệ sĩ ("hương") khớp mọi video.
            title = f" {normalize_name(v['title'])} "
            out.append((title.replace(f" {artist} ", " ") if artist else title, int(v["view_count"])))
    return out


def _views(name: str, videos: list[tuple[str, int]]) -> int:
    base = _base_title(name)
    # Tên quá ngắn ("Em", "Yêu") khớp nhầm rất nhiều tiêu đề.
    if len(base) < 4:
        return 0
    return max((v for t, v in videos if f" {base} " in t), default=0)


def top_track_albums(client: SpotifyClient, aid: str) -> list[str]:
    if not client.top_tracks_ok:
        return []
    try:
        data = client.get(f"/artists/{aid}/top-tracks", {"market": client.market})
    except requests.HTTPError as ex:
        if ex.response is not None and ex.response.status_code in (403, 404, 410):
            client.top_tracks_ok = False
            print("  ⚠ App Spotify không dùng được top-tracks; xếp hạng release bằng lượt xem YouTube.")
            return []
        raise
    out: list[str] = []
    for t in data.get("tracks", []):
        album_id = (t.get("album") or {}).get("id")
        if album_id and album_id not in out:
            out.append(album_id)
    return out


def select_top(releases: list[dict], top: int) -> list[dict]:
    """Ưu tiên: top-tracks của Spotify → lượt xem MV YouTube cùng tên → album trước single → mới hơn; mỗi tên bài chỉ lấy 1 bản."""
    if top <= 0:
        return releases
    ordered = sorted(releases, key=lambda r: r.get("release_date") or "", reverse=True)
    ordered.sort(
        key=lambda r: (
            r.get("top_track_rank") or 999,
            bool(VERSION_WORDS.search(r.get("name") or "") or SHOW_RELEASE.search(r.get("name") or "")),
            -(r.get("youtube_views") or 0),
            r.get("album_group") == "appears_on",
            r.get("album_type") != "album",
        )
    )
    chosen, seen = [], set()
    for r in ordered:
        key = _base_title(r.get("name")) or r["album_id"]
        if key in seen:
            continue
        seen.add(key)
        chosen.append(r)
        if len(chosen) == top:
            break
    return chosen


def _fetch_album(client: SpotifyClient, seed: dict, aid: str, album_id: str, group: str | None) -> dict:
    full = client.get(f"/albums/{album_id}", {"market": client.market})
    tracks = list(full.get("tracks", {}).get("items", []))
    nxt = full.get("tracks", {}).get("next")
    while nxt:
        page = client.get(nxt)
        tracks.extend(page.get("items", []))
        nxt = page.get("next")
    group = group or full.get("album_type")
    if group == "appears_on":
        # Chỉ giữ bài có nghệ sĩ seed; không suy quan hệ từ việc cùng nằm trong một tuyển tập.
        tracks = [t for t in tracks if any(x.get("id") == aid for x in t.get("artists", []))]
    return {
        "album_id": full["id"],
        "platform": "spotify",
        "seed_id": seed["seed_id"],
        "seed_artist_id": aid,
        "album_group": group,
        "album_type": full.get("album_type"),
        "name": full.get("name"),
        "release_date": full.get("release_date"),
        "release_date_precision": full.get("release_date_precision"),
        "label": full.get("label"),
        "copyrights": [{"text": c.get("text"), "type": c.get("type")} for c in full.get("copyrights") or []],
        "upc": (full.get("external_ids") or {}).get("upc"),
        "artists": _artists(full.get("artists")),
        "total_tracks": full.get("total_tracks"),
        "url": full.get("external_urls", {}).get("spotify"),
        "tracks": [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "disc_number": t.get("disc_number"),
                "track_number": t.get("track_number"),
                "duration_ms": t.get("duration_ms"),
                "explicit": t.get("explicit"),
                "artists": _artists(t.get("artists")),
                "url": t.get("external_urls", {}).get("spotify"),
            }
            for t in tracks
        ],
        "collected_at": now_iso(),
    }


def _list_releases(client: SpotifyClient, seed: dict, aid: str) -> list[dict]:
    listed = JsonlStore(RAW_SP / "releases_listed.jsonl", "artist_id")
    store = JsonlStore(RAW_SP / "releases" / f"{aid}.jsonl", "album_id")
    if aid in listed:
        return list(store.read())
    videos = youtube_views(seed.get("youtube_channel_id", ""), seed.get("name", ""))
    top_albums = top_track_albums(client, aid)
    releases, out_of_period = [], 0
    for alb in client.paged(f"/artists/{aid}/albums", {"include_groups": INCLUDE_GROUPS, "market": client.market}, limit=50):
        if not release_in_period(alb.get("release_date"), alb.get("release_date_precision")):
            out_of_period += 1
            continue
        releases.append(
            {
                "album_id": alb["id"],
                "platform": "spotify",
                "seed_id": seed["seed_id"],
                "seed_artist_id": aid,
                "album_group": alb.get("album_group") or alb.get("album_type"),
                "album_type": alb.get("album_type"),
                "name": alb.get("name"),
                "release_date": alb.get("release_date"),
                "release_date_precision": alb.get("release_date_precision"),
                "artists": _artists(alb.get("artists")),
                "total_tracks": alb.get("total_tracks"),
                "url": alb.get("external_urls", {}).get("spotify"),
                "top_track_rank": top_albums.index(alb["id"]) + 1 if alb["id"] in top_albums else None,
                "youtube_views": _views(alb.get("name"), videos),
                "collected_at": now_iso(),
            }
        )
    # Ghi sau khi liệt kê đủ, để lượt bị ngắt giữa chừng không để lại danh sách thiếu.
    for r in releases:
        if r["album_id"] not in store:
            store.append(r)
    listed.append({"artist_id": aid, "seed_id": seed["seed_id"], "n_releases": len(releases), "out_of_period": out_of_period, "top_tracks_used": bool(top_albums), "listed_at": now_iso()})
    return releases


def crawl_artist(client: SpotifyClient, seed: dict, top: int) -> None:
    aid = seed["spotify_artist_id"]
    profiles = JsonlStore(RAW_SP / "artists.jsonl", "artist_id")
    if aid not in profiles:
        a = client.get(f"/artists/{aid}")
        profiles.append(
            {
                "artist_id": aid,
                "seed_id": seed["seed_id"],
                "name": a.get("name"),
                "genres": a.get("genres") or [],
                "followers": (a.get("followers") or {}).get("total"),
                "popularity": a.get("popularity"),
                "url": a.get("external_urls", {}).get("spotify"),
                "collected_at": now_iso(),
            }
        )

    releases = _list_releases(client, seed, aid)
    chosen = select_top(releases, top)
    store = JsonlStore(RAW_SP / "albums" / f"{aid}.jsonl", "album_id")
    new = 0
    for r in chosen:
        if r["album_id"] in store:
            continue
        store.append(_fetch_album(client, seed, aid, r["album_id"], r.get("album_group")))
        new += 1
    log_run("spotify", seed["seed_id"], aid, "ok", new, len(chosen) - new, f"releases_in_period={len(releases)}")
    print(f"  {seed['name']}: {len(releases)} release trong giai đoạn, lấy chi tiết {len(chosen)} (+{new} mới) · tổng {client.calls} lượt gọi")


def crawl(client: SpotifyClient, seeds: list[dict], top: int = 5, max_calls: int = 0) -> None:
    targets = [s for s in seeds if s.get("spotify_artist_id")]
    print(f"Spotify: {len(targets)}/{len(seeds)} seed đã có artist ID; mỗi nghệ sĩ lấy chi tiết {top if top > 0 else 'mọi'} release")
    for seed in targets:
        if max_calls and client.calls >= max_calls:
            print(f"Dừng vì đã đạt --max-calls {max_calls}; chạy lại lệnh để làm tiếp.")
            return
        try:
            crawl_artist(client, seed, top)
        except (RateLimited, QuotaExceeded) as ex:
            log_run("spotify", seed["seed_id"], seed["spotify_artist_id"], "rate_limited", message=str(ex))
            wait = getattr(ex, "seconds", 0)
            when = f"; chạy lại sau {datetime.now(VN_TZ) + timedelta(seconds=wait):%H:%M ngày %d/%m}" if wait else ""
            # Gọi tiếp khi đang bị phạt có thể kéo dài thời gian khóa, nên dừng cả lượt.
            print(f"Dừng: {ex}{when}. Đã gọi {client.calls} lượt; dữ liệu đã lưu được giữ nguyên.")
            return
        except Exception as ex:
            log_run("spotify", seed["seed_id"], seed["spotify_artist_id"], "error", message=str(ex))
            print(f"  {seed['name']}: lỗi {ex}")
    print(f"Xong: {client.calls} lượt gọi API")
