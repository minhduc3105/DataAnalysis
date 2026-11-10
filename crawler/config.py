from datetime import date, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS_PATH = ROOT / "seeds" / "seeds.csv"
RAW_DIR = ROOT / "data" / "raw"
INTERIM_DIR = ROOT / "data" / "interim"
LOG_DIR = ROOT / "logs"

PERIOD_START = date(2016, 1, 1)
PERIOD_END = date(2026, 10, 21)

VN_TZ = timezone(timedelta(hours=7))
