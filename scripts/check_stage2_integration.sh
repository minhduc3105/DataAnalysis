#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"

uv run python main.py doctor --neo4j --model
uv run python main.py neo4j check

uv run python - "$API_BASE_URL" <<'PY'
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from dotenv import load_dotenv

load_dotenv()

base = sys.argv[1].rstrip("/")

def get(path):
    request = Request(base + path, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read()), response.status
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(f"FAIL {path}: {exc}") from exc

health, status = get("/api/health")
if status != 200 or health.get("ok") is not True:
    raise SystemExit(f"FAIL /api/health: {health}")
print(f"PASS /api/health — {health.get('entities')} entity")

for path, expected in (
    ("/api/feed?limit=5", list),
    ("/api/watchlists", list),
    ("/api/alerts", list),
    ("/api/trends?days=30", dict),
    ("/api/analysis/snapshots", list),
):
    payload, _ = get(path)
    if not isinstance(payload, expected):
        raise SystemExit(f"FAIL {path}: expected {expected.__name__}, got {type(payload).__name__}")
    print(f"PASS {path} — {len(payload)} item" if isinstance(payload, list) else f"PASS {path}")

snapshots, _ = get("/api/analysis/snapshots")
if snapshots:
    graph_version = snapshots[0].get("graph_version")
    if not graph_version:
        raise SystemExit("FAIL analysis snapshot thiếu graph_version")
    network, _ = get(f"/api/network?graph_version={graph_version}")
    if not isinstance(network, dict) or "overview" not in network:
        raise SystemExit("FAIL /api/network thiếu bảng overview")
    print(f"PASS /api/network — graph {graph_version}")
else:
    print("SKIP /api/network — chưa có analysis snapshot; chạy analyze trước")

question = os.getenv("MUSIC_RADAR_INTEGRATION_QUESTION", "").strip()
if question:
    for method in ("graph", "vector"):
        payload = json.dumps({"question": question, "method": method, "max_hops": 3}).encode()
        request = Request(base + "/api/ask", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=180) as response:
                result = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SystemExit(f"FAIL /api/ask ({method}): {exc}") from exc
        if result.get("status") != "ok":
            raise SystemExit(f"FAIL /api/ask ({method}): status={result.get('status')}; {result.get('answer')}")
        source_ids = set(result.get("source_ids") or [])
        sources = result.get("sources") or []
        if not source_ids or not source_ids.issubset({source.get("source_id") for source in sources}):
            raise SystemExit(f"FAIL /api/ask ({method}): source IDs không khớp evidence trả về")
        if any(not source.get("url") for source in sources):
            raise SystemExit(f"FAIL /api/ask ({method}): có evidence thiếu URL nguồn")
        print(f"PASS /api/ask ({method}) — {len(source_ids)} citation hợp lệ; model {result.get('model_version')}")
else:
    print("SKIP GraphRAG/vector answer — đặt MUSIC_RADAR_INTEGRATION_QUESTION bằng một câu hỏi có đáp án trong graph")

try:
    from neo4j import GraphDatabase
except ImportError as exc:
    raise SystemExit(f"Thiếu neo4j driver: {exc}") from exc

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "neo4j://localhost:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
)
try:
    with driver.session() as session:
        gds = session.run("RETURN gds.version() AS version").single()
        if not gds:
            raise SystemExit("FAIL GDS: không trả version")
        print(f"PASS Graph Data Science — {gds['version']}")
        if os.getenv("CHECK_VECTOR_INDEXES", "1") == "1":
            rows = list(session.run("SHOW INDEXES YIELD name, state WHERE name IN $names RETURN name, state", names=["entity_name_alias", "evidence_text", "entity_embedding", "evidence_embedding"]))
            states = {row["name"]: row["state"] for row in rows}
            missing = {name for name in ("entity_name_alias", "evidence_text", "entity_embedding", "evidence_embedding") if states.get(name) != "ONLINE"}
            if missing:
                raise SystemExit(f"FAIL indexes Neo4j thiếu/chưa ONLINE: {sorted(missing)}; chạy `neo4j indexes`, `neo4j embed`, đợi index ONLINE rồi thử lại")
            print("PASS Neo4j full-text/vector indexes — ONLINE")
finally:
    driver.close()

print("Tích hợp đọc-only đạt; không ghi thay đổi vào Neo4j.")
PY
