"""Editorial API must not inflate counts or claim pending show links are verified."""

from datetime import datetime

from crawler.config import VN_TZ
from app.api.magazine import create_router


def test_magazine_counts_documents_once_and_keeps_roster_status():
    today = datetime.now(VN_TZ).date().isoformat()
    calls = []

    def fake_run(query, **params):
        calls.append(params)
        if "CONTESTANT_ON" in query:
            return [
                {"id": "ART_1", "name": "Nghệ sĩ A", "show_name": "Anh Trai Say Hi mùa 1", "verification_status": "chờ kiểm tra"},
                {"id": "ART_1", "name": "Nghệ sĩ A", "show_name": "Anh Trai Say Hi mùa 2", "verification_status": "chờ kiểm tra"},
            ]
        return [
            {"document_id": "DOC_1", "title": "Bản nhạc mới", "url": "https://example.org/one", "source": "Nguồn",
             "platform": "web", "published_at": today, "collected_at": today, "summary": None, "image_url": "https://example.org/photo.jpg",
             "image_credit": "Tác giả", "image_source_url": "https://example.org/photo", "image_license": None,
             "artist_id": "ART_1", "artist_name": "Nghệ sĩ A", "relation": "PERFORMED", "related_name": "Bài hát",
             "quote": "Nghệ sĩ A trình bày Bài hát", "relation_id": "REL_1"},
            {"document_id": "DOC_1", "title": "Bản nhạc mới", "url": "https://example.org/one", "source": "Nguồn",
             "platform": "web", "published_at": today, "collected_at": today, "summary": None, "image_url": "https://example.org/photo.jpg",
             "image_credit": "Tác giả", "image_source_url": "https://example.org/photo", "image_license": None,
             "artist_id": "ART_1", "artist_name": "Nghệ sĩ A", "relation": "COMPOSED", "related_name": "Bài hát",
             "quote": "Nghệ sĩ A sáng tác Bài hát", "relation_id": "REL_2"},
        ]

    router = create_router(fake_run)
    routes = {route.path: route.endpoint for route in router.routes}
    shows = routes["/api/magazine/shows"]()
    assert len(shows) == 9
    assert shows[0]["artist_count"] == 1
    assert shows[1]["artist_count"] == 1
    result = routes["/api/magazine/articles"](days=30, show_id="SHOW_001", artist_id=None, source=None,
                                                  activity=None, date_from=None, date_to=None, limit=20, offset=0)
    assert result["total"] == 1
    assert result["top_artists"] == [{"id": "ART_1", "name": "Nghệ sĩ A", "documents": 1}]
    assert result["activity"] == [{"name": "Tác phẩm", "documents": 1}]
    assert len(result["items"][0]["relations"]) == 2
    assert result["items"][0]["image_url"] is None
    assert result["roster_status"] == "needs_review"
    assert calls[-1]["artist_ids"] == ["ART_1"]
