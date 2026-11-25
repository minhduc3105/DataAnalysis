"""Opt-in daily runner for the live news lane (07:00 Vietnam time)."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from . import documents, web, web_clean, youtube
from .common import read_seeds
from .config import RAW_DIR, VN_TZ
from .scope import Scope

CHECKPOINT = RAW_DIR / "web" / "live_checkpoint.json"
LIVE_START = date(2026, 10, 22)


def _load_checkpoint() -> date:
    try:
        value = json.loads(CHECKPOINT.read_text(encoding="utf-8"))["last_successful_through"]
        return date.fromisoformat(value)
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return LIVE_START


def _youtube_batch(limit: int = 75, max_videos: int = 50) -> dict:
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return {"status": "skipped_no_api_key", "channels": 0, "errors": 0, "checkpoint_advanced": False}
    seeds = read_seeds()
    verified = [s for s in seeds if s.get("youtube_channel_id") and s.get("youtube_verified") in {"có", "thủ công"}]
    if not verified:
        return {"status": "no_verified_channels", "channels": 0, "errors": 0, "checkpoint_advanced": False}
    try:
        checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        checkpoint = {}
    offset = int(checkpoint.get("youtube_offset", 0)) % len(verified)
    batch = (verified[offset:] + verified[:offset])[:min(limit, len(verified))]
    session = requests.Session()
    scope = Scope(seeds)
    errors = []
    for seed in batch:
        try:
            youtube.crawl_api(seed, api_key, max_videos, session, scope, after_only=True)
        except Exception as exc:
            errors.append({"seed_id": seed.get("seed_id"), "error": str(exc)[:300]})
            if isinstance(exc, youtube.QuotaExceeded):
                break
    success = not errors
    if success:
        try:
            documents.build_live(seeds)
        except Exception as exc:
            errors.append({"step": "build_live_documents", "error": str(exc)[:300]})
            success = False
    result = {"status": "ok" if success else "partial", "channels": len(batch), "errors": errors, "checkpoint_advanced": success, "next_offset": (offset + len(batch)) % len(verified)}
    if success:
        checkpoint["youtube_offset"] = result["next_offset"]
        checkpoint["youtube_updated_at"] = datetime.now(VN_TZ).isoformat()
        CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        temp = CHECKPOINT.with_suffix(".tmp")
        temp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(CHECKPOINT)
    return result


def run_once(date_from: str | None = None, date_to: str | None = None, limit: int = 200, search_limit: int = 50) -> dict:
    start = date.fromisoformat(date_from) if date_from else _load_checkpoint()
    end = date.fromisoformat(date_to) if date_to else datetime.now(VN_TZ).date()
    if start < LIVE_START or end > date.today() or start > end:
        raise ValueError(f"Khoảng ngày luồng mới phải từ {LIVE_START} đến hôm nay")
    web.discover(limit_per_source=limit, search_limit=search_limit, date_from=start.isoformat(), date_to=end.isoformat(), force=True, stream=True)
    search_path = web.INTERIM_DIR / "web_live_search_report.json"
    search = json.loads(search_path.read_text(encoding="utf-8")) if search_path.exists() else {"errors": 1}
    web.crawl(limit=limit, resolve_limit=min(limit, 100), workers=4, stream=True)
    crawl_path = web.INTERIM_DIR / "web_live_crawl_report.json"
    crawl = json.loads(crawl_path.read_text(encoding="utf-8")) if crawl_path.exists() else {"errors": 1}
    web_clean.clean(lane="live")
    success = not search.get("errors", 0) and not crawl.get("errors", 0)
    youtube_result = _youtube_batch()
    result = {"period": [start.isoformat(), end.isoformat()], "search_errors": search.get("errors", 0), "crawl_errors": crawl.get("errors", 0), "checkpoint_advanced": success, "youtube": youtube_result}
    if success:
        CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        temp = CHECKPOINT.with_suffix(".tmp")
        try:
            checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            checkpoint = {}
        checkpoint.update({"last_successful_through": end.isoformat(), "updated_at": datetime.now(VN_TZ).isoformat()})
        temp.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(CHECKPOINT)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run() -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as exc:
        raise SystemExit("Cài dependency bằng `uv sync --locked` để bật APScheduler") from exc
    scheduler = BlockingScheduler(timezone=ZoneInfo("Asia/Ho_Chi_Minh"))
    scheduler.add_job(run_once, "cron", hour=7, minute=0, id="live-news-daily", max_instances=1, coalesce=True, misfire_grace_time=3600)
    print("Lịch luồng báo mới đã bật: mỗi ngày 07:00 Asia/Ho_Chi_Minh. Dừng bằng Ctrl+C.")
    scheduler.start()
