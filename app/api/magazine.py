"""Read-only editorial views over documented activity of selected show artists."""

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import csv

from fastapi import APIRouter, HTTPException, Query

from crawler.config import VN_TZ


SHOW_IDS = ("SHOW_001", "SHOW_002", "SHOW_003", "SHOW_004", "SHOW_005", "SHOW_006", "SHOW_015", "SHOW_016", "SHOW_029")
SEED_PATH = Path(__file__).resolve().parents[2] / "seeds" / "shows.csv"
ACTIVITY = {
    "PERFORMED": "Tác phẩm", "COMPOSED": "Tác phẩm", "PRODUCED": "Tác phẩm", "TRACK_OF": "Tác phẩm",
    "FEATURED_ON": "Hợp tác", "COLLABORATED_WITH": "Hợp tác", "PERFORMED_AT": "Biểu diễn",
    "CONTESTANT_ON": "Chương trình", "DISPUTED_WITH": "Tranh chấp", "AMBASSADOR_OF": "Thương hiệu",
}


def _show_catalog() -> list[dict]:
    with SEED_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["show_id"]: row for row in csv.DictReader(handle)}
    shows = []
    for show_id in SHOW_IDS:
        row = rows[show_id]
        title = f"{row['show_name']} mùa {row['season']}" if row["season"] else f"{row['show_name']} {row['year']}"
        shows.append({"id": show_id, "name": title, "year": row["year"], "source_status": row["verification_status"]})
    return shows


def create_router(run):
    router = APIRouter(prefix="/api/magazine", tags=["magazine"])

    def roster() -> tuple[list[dict], list[dict]]:
        shows = _show_catalog()
        rows = run("""
            MATCH (artist:Entity:Person)-[r:CONTESTANT_ON]->(show:Entity:Show)
            WHERE show.name IN $names
            RETURN artist.entity_id AS id, artist.name AS name, show.name AS show_name,
                   r.verification_status AS verification_status
            ORDER BY artist.name
        """, names=[show["name"] for show in shows])
        by_name = {show["name"]: show for show in shows}
        artists: dict[str, dict] = {}
        for row in rows:
            show = by_name[row["show_name"]]
            item = artists.setdefault(row["id"], {"id": row["id"], "name": row["name"], "shows": [], "verified_shows": []})
            if show["id"] not in item["shows"]:
                item["shows"].append(show["id"])
            if row.get("verification_status") in ("đã xác minh", "đã duyệt", "verified", "approved"):
                item["verified_shows"].append(show["id"])
        for show in shows:
            show["artist_count"] = sum(show["id"] in item["shows"] for item in artists.values())
            show["verified_artist_count"] = sum(show["id"] in item["verified_shows"] for item in artists.values())
        return shows, list(artists.values())

    @router.get("/shows")
    def shows():
        return roster()[0]

    @router.get("/artists")
    def artists(show_id: str | None = None):
        shows, people = roster()
        if show_id and show_id not in {show["id"] for show in shows}:
            raise HTTPException(400, "Show không thuộc phạm vi tạp chí")
        return [person for person in people if not show_id or show_id in person["shows"]]

    def articles_data(days: int, show_id: str | None, artist_id: str | None, source: str | None,
                      activity: str | None = None, date_from: str | None = None, date_to: str | None = None):
        shows, people = roster()
        if show_id and show_id not in {show["id"] for show in shows}:
            raise HTTPException(400, "Show không thuộc phạm vi tạp chí")
        selected = {person["id"]: person for person in people if not show_id or show_id in person["shows"]}
        if artist_id:
            selected = {artist_id: selected[artist_id]} if artist_id in selected else {}
        today = datetime.now(VN_TZ).date()
        since = today - timedelta(days=days - 1)
        until = today + timedelta(days=1)
        documents: dict[str, dict] = {}
        if selected:
            rows = run("""
                MATCH (artist:Entity)-[r]-(other:Entity)
                WHERE artist.entity_id IN $artist_ids AND r.relation_id IS NOT NULL
                MATCH (e:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
                WHERE d.published_at >= $since AND d.published_at < $until
                  AND ($source IS NULL OR toLower(coalesce(d.source_name,'')) CONTAINS toLower($source))
                RETURN d.document_id AS document_id, d.title AS title, d.url AS url,
                       d.source_name AS source, d.platform AS platform, d.published_at AS published_at,
                       d.collected_at AS collected_at, d.summary AS summary, d.image_url AS image_url,
                       d.image_credit AS image_credit, d.image_source_url AS image_source_url,
                       d.image_license AS image_license,
                       artist.entity_id AS artist_id, artist.name AS artist_name,
                       type(r) AS relation, other.name AS related_name, e.quote AS quote,
                       e.relation_id AS relation_id
                ORDER BY d.published_at DESC, d.document_id
            """, artist_ids=list(selected), since=since.isoformat(), until=until.isoformat(), source=source)
            for row in rows:
                doc_id = row["document_id"]
                if not doc_id:
                    continue
                item = documents.setdefault(doc_id, {key: row.get(key) for key in (
                    "document_id", "title", "url", "source", "platform", "published_at", "collected_at",
                    "summary", "image_url", "image_credit", "image_source_url", "image_license")})
                if not (str(item.get("image_url") or "").startswith(("https://", "http://")) and item.get("image_credit") and
                        str(item.get("image_source_url") or "").startswith(("https://", "http://")) and
                        str(item.get("image_license") or "").lower() in {"cc0", "cc by", "cc by-sa", "public domain", "permission"}):
                    item.update(image_url=None, image_credit=None, image_source_url=None, image_license=None)
                item.setdefault("artists", {})[row["artist_id"]] = {"id": row["artist_id"], "name": row["artist_name"], "shows": selected[row["artist_id"]]["shows"]}
                item.setdefault("relations", {})[row["relation_id"]] = {
                    "relation_id": row["relation_id"], "relation": row["relation"], "artist_id": row["artist_id"],
                    "artist_name": row["artist_name"], "related_name": row["related_name"], "quote": row["quote"]}
        items = []
        daily = Counter()
        artist_docs: dict[str, set[str]] = {}
        activity_docs: dict[str, set[str]] = {}
        for item in documents.values():
            item["artists"] = list(item.get("artists", {}).values())
            item["relations"] = list(item.get("relations", {}).values())
            item["activity"] = sorted({ACTIVITY.get(relation["relation"], "Hoạt động khác") for relation in item["relations"]})
            item["excerpt"] = next((relation["quote"] for relation in item["relations"] if relation["quote"]), None)
            if activity and activity not in item["activity"]:
                continue
            day = str(item["published_at"])[:10]
            if (date_from and day < date_from) or (date_to and day > date_to):
                continue
            items.append(item)
            daily[str(item["published_at"])[:10]] += 1
            for artist in item["artists"]:
                artist_docs.setdefault(artist["id"], set()).add(item["document_id"])
            for kind in item["activity"]:
                activity_docs.setdefault(kind, set()).add(item["document_id"])
        items.sort(key=lambda item: (item["published_at"] or "", item["document_id"]), reverse=True)
        return {
            "shows": shows, "items": items, "total": len(items),
            "period": {"from": since.isoformat(), "to": today.isoformat(), "days": days},
            "daily": [{"date": (since + timedelta(days=i)).isoformat(), "documents": daily[(since + timedelta(days=i)).isoformat()]} for i in range(days)],
            "top_artists": sorted(({"id": key, "name": selected[key]["name"], "documents": len(ids)} for key, ids in artist_docs.items()), key=lambda row: (-row["documents"], row["name"])),
            "activity": sorted(({"name": key, "documents": len(ids)} for key, ids in activity_docs.items()), key=lambda row: (-row["documents"], row["name"])),
            "roster_status": "confirmed" if selected and all(
                show in person["verified_shows"] for person in selected.values()
                for show in person["shows"] if not show_id or show == show_id
            ) else "needs_review",
        }

    @router.get("/articles")
    def articles(days: int = Query(30, ge=7, le=90), show_id: str | None = None, artist_id: str | None = None,
                 source: str | None = None, activity: str | None = None, date_from: str | None = None,
                 date_to: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        if date_from and date_to and date_from > date_to:
            raise HTTPException(400, "Khoảng ngày không hợp lệ")
        data = articles_data(days, show_id, artist_id, source, activity, date_from, date_to)
        data["items"] = data["items"][offset:offset + limit]
        return data

    @router.get("/articles/{document_id}")
    def article(document_id: str):
        # The longest supported window keeps this view consistent with the dated magazine feed.
        data = articles_data(90, None, None, None)
        for item in data["items"]:
            if item["document_id"] == document_id:
                return item
        raise HTTPException(404, "Chưa có tài liệu này trong tạp chí 90 ngày")

    return router
