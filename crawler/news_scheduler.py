"""Persistent daily news and YouTube updates plus a budgeted weekly Spotify refresh."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import content_classification, documents, spotify, web, web_clean, youtube
from .common import read_seeds
from .config import RAW_DIR, VN_TZ
from .scope import Scope

CHECKPOINT = RAW_DIR / "web" / "live_checkpoint.json"
SPOTIFY_CHECKPOINT = RAW_DIR / "spotify" / "live_checkpoint.json"
STATUS_PATH = RAW_DIR / "live_update_status.json"
SCHEDULER_STATUS_PATH = RAW_DIR / "live_scheduler_status.json"
COVERAGE_PATH = RAW_DIR / "collection_coverage.jsonl"
LOCK_PATH = RAW_DIR / "live_update.lock"
LIVE_START = date(2026, 10, 22)


def _load_checkpoint() -> date:
    try:
        value = json.loads(CHECKPOINT.read_text(encoding="utf-8"))["last_successful_through"]
        return date.fromisoformat(value)
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return LIVE_START


def _write_status(state: dict) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    payload = {**state, "updated_at": datetime.now(VN_TZ).isoformat(timespec="seconds"), "timezone": "Asia/Ho_Chi_Minh"}
    temp = STATUS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATUS_PATH)


@contextmanager
def _job_lock():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        try:
            yield True
        finally:
            lock.seek(0)
            lock.truncate()
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _publish_scheduler_heartbeat(scheduler) -> None:
    now = datetime.now(VN_TZ).isoformat(timespec="seconds")
    jobs = {}
    for job in scheduler.get_jobs():
        if job.id == "scheduler-heartbeat":
            continue
        next_run = getattr(job, "next_run_time", None)
        if next_run is None:
            next_run = job.trigger.get_next_fire_time(None, datetime.now(VN_TZ))
        jobs[job.id] = next_run.astimezone(VN_TZ).isoformat(timespec="seconds") if next_run else None
    _atomic_json(SCHEDULER_STATUS_PATH, {"status": "running", "heartbeat_at": now, "timezone": "Asia/Ho_Chi_Minh", "next_runs": jobs})


def _record_coverage(start: date, end: date, complete: bool, steps: dict) -> None:
    """Persist explicit daily collection coverage, including successful zero-result days."""
    existing = {}
    try:
        with COVERAGE_PATH.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    existing[row["date"]] = row
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    covered_at = datetime.now(VN_TZ).isoformat(timespec="seconds")
    current = start
    while current <= end:
        day = current.isoformat()
        existing[day] = {"date": day, "complete": complete, "steps": steps, "covered_at": covered_at, "timezone": "Asia/Ho_Chi_Minh"}
        current = date.fromordinal(current.toordinal() + 1)
    COVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = COVERAGE_PATH.with_suffix(".tmp")
    temp.write_text("".join(json.dumps(existing[key], ensure_ascii=False) + "\n" for key in sorted(existing)), encoding="utf-8")
    temp.replace(COVERAGE_PATH)


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
    result = {"status": "ok" if success else "partial", "channels": len(batch), "errors": errors, "checkpoint_advanced": success, "next_offset": (offset + len(batch)) % len(verified)}
    if success:
        checkpoint["youtube_offset"] = result["next_offset"]
        checkpoint["youtube_updated_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")
        _atomic_json(CHECKPOINT, checkpoint)
    return result


def run_once(date_from: str | None = None, date_to: str | None = None, limit: int = 200, search_limit: int = 50) -> dict:
    with _job_lock() as acquired:
        if not acquired:
            return {"status": "already_running", "checkpoint_advanced": False}
        start = date.fromisoformat(date_from) if date_from else _load_checkpoint()
        end = date.fromisoformat(date_to) if date_to else datetime.now(VN_TZ).date()
        if start < LIVE_START or end > datetime.now(VN_TZ).date() or start > end:
            raise ValueError(f"Khoảng ngày luồng tin mới phải từ {LIVE_START} đến hôm nay")
        state = {"status": "running", "period": [start.isoformat(), end.isoformat()], "steps": {}}
        _write_status(state)
        try:
            state["steps"]["web_discovery"] = {"status": "running"}
            _write_status(state)
            web.discover(limit_per_source=limit, search_limit=search_limit, date_from=start.isoformat(), date_to=end.isoformat(), force=True, stream=True)
            search_path = web.INTERIM_DIR / "web_live_search_report.json"
            search = json.loads(search_path.read_text(encoding="utf-8")) if search_path.exists() else {"errors": 1}
            state["steps"]["web_discovery"] = {"status": "ok" if not search.get("errors", 0) else "partial", "errors": search.get("errors", 0)}
            state["steps"]["web_crawl"] = {"status": "running"}
            _write_status(state)
            web.crawl(limit=limit, resolve_limit=min(limit, 100), workers=4, stream=True)
            crawl_path = web.INTERIM_DIR / "web_live_crawl_report.json"
            crawl = json.loads(crawl_path.read_text(encoding="utf-8")) if crawl_path.exists() else {"errors": 1}
            state["steps"]["web_crawl"] = {"status": "ok" if not crawl.get("errors", 0) else "partial", "errors": crawl.get("errors", 0)}
            web_clean.clean(lane="live")
            quality_path = web.INTERIM_DIR / "web_live_quality_report.json"
            quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
            state["steps"]["normalize_and_review"] = {"status": "ok", "ready": quality.get("clean", 0), "pending_review": quality.get("review", 0), "rejected": quality.get("rejected", 0)}
            yt = _youtube_batch()
            state["steps"]["youtube"] = yt
            documents.build_live(read_seeds())
            state["steps"]["live_documents"] = {"status": "ok", "note": "Tài liệu được dựng trong lane mới; quan hệ chỉ xuất hiện trên đồ thị sau khi được duyệt và nạp."}
            try:
                state["steps"]["content_classification"] = content_classification.classify_pending()
            except Exception as exc:
                state["steps"]["content_classification"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            state["steps"]["relation_extraction"] = {"status": "awaiting_external_handoff", "note": "Kết quả trích xuất quan hệ cần được cung cấp trong model_handoff; chưa tự xác nhận quan hệ."}
            state["steps"]["validation"] = {"status": "waiting_for_extraction"}
            state["steps"]["relation_review"] = {"status": "pending_manual_review", "pending": quality.get("review", 0)}
            state["steps"]["import_approved"] = {"status": "manual_step_required", "note": "Chỉ nạp các quan hệ đã duyệt bằng stage2 apply."}
            state["steps"]["research_snapshot"] = {"status": "preserved", "note": "Lịch luồng mới không ghi đè snapshot nghiên cứu."}
            web_success = not search.get("errors", 0) and not crawl.get("errors", 0)
            daily_sources_complete = web_success and yt.get("checkpoint_advanced", False)
            _record_coverage(start, end, daily_sources_complete, {"web_discovery": state["steps"]["web_discovery"], "web_crawl": state["steps"]["web_crawl"], "youtube": yt})
            all_daily_sources_ok = web_success and yt.get("checkpoint_advanced", False)
            state["status"] = "awaiting_review" if all_daily_sources_ok else ("partial_failure" if not web_success or yt.get("errors") else "awaiting_review_with_source_gaps")
            state["checkpoint_advanced"] = web_success
            if web_success:
                try:
                    previous = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    previous = {}
                previous.update({"last_successful_through": end.isoformat(), "updated_at": datetime.now(VN_TZ).isoformat(timespec="seconds")})
                _atomic_json(CHECKPOINT, previous)
        except Exception as exc:
            state["status"] = "failed"
            state["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            state["checkpoint_advanced"] = False
            raise
        finally:
            _write_status(state)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return state


def run_spotify_weekly(max_calls: int | None = None) -> dict:
    with _job_lock() as acquired:
        if not acquired:
            return {"status": "already_running", "checkpoint_advanced": False}
        cap = max_calls if max_calls is not None else int(os.getenv("SPOTIFY_WEEKLY_MAX_CALLS", "40"))
        try:
            client = spotify.SpotifyClient.from_env()
        except SystemExit as exc:
            result = {"status": "skipped_missing_credentials", "message": str(exc), "checkpoint_advanced": False}
            _atomic_json(SPOTIFY_CHECKPOINT, {**result, "updated_at": datetime.now(VN_TZ).isoformat(timespec="seconds")})
            _write_status({"status": "skipped_missing_credentials", "steps": {"spotify": result}})
            return result
        state = {"status": "running", "steps": {"spotify": {"status": "running", "budget": cap}}}
        _write_status(state)
        try:
            seeds = read_seeds()
            crawl_result = spotify.crawl_live(client, seeds, max_calls=cap)
            documents.build_live(seeds)
            try:
                state["steps"]["content_classification"] = content_classification.classify_pending()
            except Exception as exc:
                state["steps"]["content_classification"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            success = crawl_result.get("checkpoint_advanced", False)
            result = {**crawl_result, "status": "awaiting_review" if success else crawl_result["status"], "updated_at": datetime.now(VN_TZ).isoformat(timespec="seconds")}
            if success:
                _atomic_json(SPOTIFY_CHECKPOINT, result)
            state["status"] = "awaiting_review" if success else "partial_failure"
            state["steps"]["spotify"] = {**crawl_result, "status": "ok" if success else "partial"}
        except Exception as exc:
            state["status"] = "failed"
            state["steps"]["spotify"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
            result = {"status": "failed", "error": state["steps"]["spotify"]["error"], "checkpoint_advanced": False}
            raise
        finally:
            _write_status(state)
        return result


def run() -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError as exc:
        raise SystemExit("Cài dependency bằng `uv sync --locked` để bật APScheduler") from exc
    scheduler = BlockingScheduler(timezone=ZoneInfo("Asia/Ho_Chi_Minh"))
    scheduler.add_job(run_once, "cron", hour=7, minute=0, id="live-news-daily", max_instances=1, coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(run_spotify_weekly, "cron", day_of_week="mon", hour=7, minute=0, id="live-spotify-weekly", max_instances=1, coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(lambda: _publish_scheduler_heartbeat(scheduler), "interval", minutes=1, id="scheduler-heartbeat", max_instances=1, coalesce=True)
    _publish_scheduler_heartbeat(scheduler)
    print("Lịch luồng báo và YouTube: mỗi ngày 07:00; Spotify: thứ Hai 07:00 Asia/Ho_Chi_Minh. Tiến trình riêng, dừng bằng Ctrl+C.")
    try:
        scheduler.start()
    finally:
        _atomic_json(SCHEDULER_STATUS_PATH, {"status": "stopped", "heartbeat_at": datetime.now(VN_TZ).isoformat(timespec="seconds"), "timezone": "Asia/Ho_Chi_Minh"})
