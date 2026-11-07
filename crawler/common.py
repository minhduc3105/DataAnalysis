import csv
import json
import random
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator

from .config import LOG_DIR, PERIOD_END, PERIOD_START, SEEDS_PATH, VN_TZ

SEED_COLUMNS = [
    "seed_id",
    "name",
    "entity_type",
    "genre_group",
    "youtube_channel_id",
    "youtube_channel_name",
    "youtube_verified",
    "spotify_artist_id",
    "spotify_name",
    "verification_status",
    "checked_at",
    "notes",
    "layer",
    "source_key",
    "discovered_in",
    "aliases",
]


def now_iso() -> str:
    return datetime.now(VN_TZ).isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now(VN_TZ).date().isoformat()


def parse_date(value: str | None) -> date | None:
    """Nhận YYYYMMDD, YYYY-MM-DD, YYYY-MM hoặc YYYY (độ chính xác ngày phát hành Spotify)."""
    if not value:
        return None
    value = value.strip()
    if "T" in value:
        # Mốc giai đoạn tính theo giờ Việt Nam; API trả UTC nên phải đổi múi giờ trước khi lấy ngày.
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(VN_TZ).date()
        except ValueError:
            pass
    value = value[:10]
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def in_period(d: date | None) -> bool:
    return d is not None and PERIOD_START <= d <= PERIOD_END


def release_in_period(value: str | None, precision: str | None) -> bool:
    """Ngày chỉ có năm/tháng phải nằm trọn trong giai đoạn, vì không biết ngày thật."""
    start = parse_date(value)
    if start is None:
        return False
    if precision == "year":
        end = date(start.year, 12, 31)
    elif precision == "month":
        end = (date(start.year + start.month // 12, start.month % 12 + 1, 1) - timedelta(days=1))
    else:
        end = start
    return start >= PERIOD_START and end <= PERIOD_END


def normalize_name(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").casefold()
    text = text.replace("đ", "d")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def polite_sleep(low: float, high: float) -> None:
    time.sleep(random.uniform(low, high))


def read_seeds(path: Path = SEEDS_PATH) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_seeds(rows: list[dict], path: Path = SEEDS_PATH) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SEED_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    for attempt in range(30):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            # Excel khóa file khi đang mở; chờ người dùng đóng thay vì làm mất kết quả đã dò.
            if attempt == 0:
                print(f"  ⚠ {path.name} đang bị mở ở chương trình khác (Excel?). Hãy đóng file, tool sẽ thử lại trong 60 giây...", flush=True)
            time.sleep(2)
    print(f"  ⚠ Chưa ghi được {path.name}; kết quả đang nằm ở {tmp.name}, lần lưu sau sẽ thử lại.", flush=True)


def select_seeds(seeds: list[dict], seed_ids: list[str] | None, types: set[str]) -> list[dict]:
    chosen = [s for s in seeds if s["entity_type"] in types]
    if seed_ids:
        wanted = set(seed_ids)
        chosen = [s for s in chosen if s["seed_id"] in wanted]
    return chosen


def merge_candidates(path: Path, rows: list[dict], seed_ids: set[str]) -> None:
    old = []
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            old = [r for r in csv.DictReader(f) if r["seed_id"] not in seed_ids]
    merged = old + rows
    if not merged:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(merged[-1].keys()))
        writer.writeheader()
        writer.writerows(merged)


class JsonlStore:
    """File JSONL chỉ ghi nối; khóa đã có được nạp lại để chạy tiếp sau khi bị ngắt."""

    def __init__(self, path: Path, key: str):
        self.path = path
        self.key = key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.keys = {rec[key] for rec in self.read() if key in rec}

    def read(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # dòng cuối có thể dở dang nếu tiến trình bị dừng giữa chừng

    def __contains__(self, item: str) -> bool:
        return item in self.keys

    def append(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.keys.add(record[self.key])


def iter_jsonl(paths: Iterable[Path]) -> Iterator[dict]:
    for p in paths:
        yield from JsonlStore(p, "_").read()


RUN_LOG_COLUMNS = ["run_at", "platform", "seed_id", "target", "status", "new_items", "skipped_items", "message"]


def log_run(platform: str, seed_id: str, target: str, status: str, new_items: int = 0, skipped_items: int = 0, message: str = "") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / "crawl_runs.csv"
    is_new = not path.exists()
    with path.open("a", encoding="utf-8-sig" if is_new else "utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(RUN_LOG_COLUMNS)
        writer.writerow([now_iso(), platform, seed_id, target, status, new_items, skipped_items, message[:500]])
