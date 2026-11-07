import base64
import os
import time

import requests

from .common import JsonlStore, log_run, merge_candidates, normalize_name, now_iso, polite_sleep, release_in_period, today_iso
from .config import INTERIM_DIR, RAW_DIR
from .net import get_json

API = "https://api.spotify.com/v1"
RAW_SP = RAW_DIR / "spotify"
INCLUDE_GROUPS = "album,single,appears_on,compilation"


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str, market: str = "VN"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.market = market
        self.session = requests.Session()
        self._token = None
        self._expires = 0.0

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
        polite_sleep(0.15, 0.4)
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


def crawl_artist(client: SpotifyClient, seed: dict) -> None:
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

    store = JsonlStore(RAW_SP / "albums" / f"{aid}.jsonl", "album_id")
    new = skipped = out_of_period = 0
    for alb in client.paged(f"/artists/{aid}/albums", {"include_groups": INCLUDE_GROUPS, "market": client.market}, limit=50):
        if alb["id"] in store:
            skipped += 1
            continue
        if not release_in_period(alb.get("release_date"), alb.get("release_date_precision")):
            out_of_period += 1
            continue
        full = client.get(f"/albums/{alb['id']}", {"market": client.market})
        tracks = list(full.get("tracks", {}).get("items", []))
        nxt = full.get("tracks", {}).get("next")
        while nxt:
            page = client.get(nxt)
            tracks.extend(page.get("items", []))
            nxt = page.get("next")
        group = alb.get("album_group") or full.get("album_type")
        if group == "appears_on":
            # Chỉ giữ bài có nghệ sĩ seed; không suy quan hệ từ việc cùng nằm trong một tuyển tập.
            tracks = [t for t in tracks if any(x.get("id") == aid for x in t.get("artists", []))]
        store.append(
            {
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
        )
        new += 1
    log_run("spotify", seed["seed_id"], aid, "ok", new, skipped, f"out_of_period={out_of_period}")
    print(f"  {seed['name']}: +{new} release, bỏ qua {skipped}, ngoài giai đoạn {out_of_period}")


def crawl(client: SpotifyClient, seeds: list[dict]) -> None:
    targets = [s for s in seeds if s.get("spotify_artist_id")]
    print(f"Spotify: {len(targets)}/{len(seeds)} seed đã có artist ID")
    for seed in targets:
        try:
            crawl_artist(client, seed)
        except Exception as ex:
            log_run("spotify", seed["seed_id"], seed["spotify_artist_id"], "error", message=str(ex))
            print(f"  {seed['name']}: lỗi {ex}")
