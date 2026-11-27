from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from functools import lru_cache
from collections import Counter
import csv
import json
import re
from pathlib import Path
from statistics import mean, pstdev

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from crawler.analysis import OUT as ANALYSIS_DIR
from crawler.graphdb import connect
from crawler.model_contract import RELATION_SIGNATURES
from crawler import retrieval
from crawler.config import VN_TZ, RAW_DIR, INTERIM_DIR
from app.api.magazine import create_router as create_magazine_router

load_dotenv()
DRIVER = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    DRIVER["neo4j"] = connect()
    yield
    DRIVER["neo4j"].close()


app = FastAPI(title="VN Music Radar API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


def run(query: str, **params) -> list[dict]:
    with DRIVER["neo4j"].session() as session:
        return [r.data() for r in session.run(query, **params)]


app.include_router(create_magazine_router(run))


@lru_cache(maxsize=256)
def _table(name: str, root: str, mtime: float) -> list[dict]:
    df = pd.read_csv(Path(root) / f"{name}.csv", encoding="utf-8-sig")
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _analysis_path(graph_version: str | None = None) -> Path:
    if graph_version is None:
        return ANALYSIS_DIR
    if not re.fullmatch(r"[0-9a-f]{16}", graph_version):
        raise HTTPException(400, "graph_version không hợp lệ")
    path = ANALYSIS_DIR / "snapshots" / f"graph-{graph_version}"
    if not path.is_dir():
        raise HTTPException(404, f"Chưa có snapshot phân tích {graph_version}")
    return path


def table(name: str, graph_version: str | None = None) -> list[dict]:
    root = _analysis_path(graph_version)
    path = root / f"{name}.csv"
    if not path.exists():
        raise HTTPException(503, f"Chưa có {path.name}; chạy `uv run python main.py analyze` trước")
    return _table(name, str(root), path.stat().st_mtime)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "entities": run("MATCH (n:Entity) RETURN count(n) AS n")[0]["n"]}


@app.get("/api/network")
def network(graph_version: str | None = None) -> dict:
    """Số liệu phân tích mạng cho trang Chân dung mạng (kết quả của lệnh analyze)."""
    return {
        name: table(name, graph_version)
        for name in [
            "overview", "collab_summary", "small_world", "distance_distribution", "small_world_paths", "community_methods",
            "small_world_reference_runs", "kcore_distribution", "centrality_correlation", "top20_overlap", "top_by_role", "pagerank_by_period",
            "pagerank_song_company", "community_bridges", "leiden_runs", "graph_enrichment_delta", "pagerank_change_after_enrichment", "relations_by_type", "nodes_by_type",
        ]
    }


@app.get("/api/analysis/snapshots")
def analysis_snapshots() -> list[dict]:
    root = ANALYSIS_DIR / "snapshots"
    snapshots = []
    for path in root.glob("graph-*") if root.exists() else []:
        manifest = path / "analysis_manifest.json"
        if not manifest.exists():
            continue
        try:
            row = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        snapshots.append(row)
    return sorted(snapshots, key=lambda row: row.get("generated_at", ""), reverse=True)


@app.get("/api/update-status")
def update_status() -> dict:
    """Trạng thái scheduler và các checkpoint thu thập, không khởi chạy crawler."""
    checkpoints = {}
    for name, path in {
        "web": RAW_DIR / "web" / "live_checkpoint.json",
        "youtube": RAW_DIR / "web" / "live_checkpoint.json",
        "spotify": RAW_DIR / "spotify" / "live_checkpoint.json",
    }.items():
        try:
            checkpoints[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            checkpoints[name] = None
    reports = {}
    for name in ("web_live_search_report", "web_live_crawl_report"):
        path = INTERIM_DIR / f"{name}.json"
        try:
            reports[name.removeprefix("web_live_")] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            reports[name.removeprefix("web_live_")] = None
    classification = _classification_status()
    default_steps = {
        name: {"status": "not_run"}
        for name in (
            "web_discovery", "web_crawl", "normalize_and_review", "youtube", "spotify",
            "live_documents", "content_classification", "relation_extraction", "validation",
            "relation_review", "import_approved",
        )
    }
    default_steps["research_snapshot"] = {"status": "preserved"}
    try:
        pipeline = json.loads((RAW_DIR / "live_update_status.json").read_text(encoding="utf-8"))
        pipeline["steps"] = {**default_steps, **pipeline.get("steps", {})}
    except (OSError, json.JSONDecodeError):
        pipeline = {"status": "not_run", "steps": default_steps}
    if pipeline["steps"].get("content_classification", {}).get("status") == "not_run":
        pipeline["steps"]["content_classification"] = {"status": classification.get("status", "not_configured")}

    def source_status(name: str, checkpoint: dict | None, step: dict | None, success_marker: str = "updated_at") -> dict:
        if step and step.get("status") not in (None, "not_run"):
            return {**step, "updated_at": pipeline.get("updated_at")}
        if checkpoint is None:
            return {"status": "not_run"}
        if name == "youtube" and not checkpoint.get("youtube_updated_at"):
            return {"status": "not_run"}
        if checkpoint.get("status") in {"skipped_missing_credentials", "skipped_no_api_key"}:
            return {"status": "not_configured", "detail": checkpoint["status"], "updated_at": checkpoint.get(success_marker)}
        if checkpoint.get("checkpoint_advanced") is False:
            return {"status": "partial", "detail": checkpoint.get("status", "checkpoint_not_advanced"), "updated_at": checkpoint.get(success_marker)}
        return {"status": "ok", "updated_at": checkpoint.get(success_marker)}

    sources = {
        "web": source_status("web", checkpoints["web"], pipeline["steps"].get("web_crawl")),
        "youtube": source_status("youtube", checkpoints["youtube"], pipeline["steps"].get("youtube"), "youtube_updated_at"),
        "spotify": source_status("spotify", checkpoints["spotify"], pipeline["steps"].get("spotify")),
    }
    return {
        "timezone": "Asia/Ho_Chi_Minh",
        "schedule": {"web": "07:00 daily", "youtube": "07:00 daily", "spotify": "Monday 07:00"},
        "checkpoints": checkpoints,
        "sources": sources,
        "reports": reports,
        "pipeline": pipeline,
        "content_classification": classification,
        "scheduler": _scheduler_status(),
        "sentiment": classification.get("status", "not_configured"),
        "topics": "model_classified" if classification.get("classified", 0) else "relation_type_derived",
        "checked_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
    }


@app.get("/api/classifications")
def classifications(limit: int = Query(100, ge=1, le=300), offset: int = Query(0, ge=0)) -> dict:
    """Versioned document classifications and source citations, separate from relation approval."""
    records = sorted(_classification_rows(), key=lambda row: row.get("classified_at") or "", reverse=True)
    page = records[offset:offset + limit]
    ids = list(dict.fromkeys(row.get("document_id") for row in page if row.get("document_id")))
    sources = run("MATCH (d:Document) WHERE d.document_id IN $ids RETURN d.document_id AS document_id,d.title AS title,d.url AS url,d.source_name AS source,d.published_at AS published_at", ids=ids) if ids else []
    source_map = {row["document_id"]: row for row in sources}
    return {
        "status": _classification_status(),
        "items": [{**row, **{key: value for key, value in source_map.get(row.get("document_id"), {}).items() if value is not None}, "topics": [value for value in (row.get("topics") or "").split("|") if value]} for row in page],
        "offset": offset,
        "limit": limit,
    }


def _compare_period(current: int, previous: int, coverage_complete: bool = True) -> dict:
    delta = current - previous
    if not coverage_complete:
        return {"current": current, "previous": previous, "delta": delta, "change_percent": None, "comparison": "incomplete_coverage"}
    if previous == 0:
        return {"current": current, "previous": previous, "delta": delta, "change_percent": None, "comparison": "new" if current else "no_baseline"}
    return {"current": current, "previous": previous, "delta": delta, "change_percent": round(delta / previous * 100, 1), "comparison": "comparable"}


def _day_in_period(value: str | None, start: date, end_exclusive: date) -> bool:
    try:
        day = date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return False
    return start <= day < end_exclusive


def _reviewed_relations_since(start: date, end_exclusive: date, source: str | None = None) -> list[dict]:
    review_types = run("CALL db.relationshipTypes() YIELD relationshipType WHERE relationshipType='REVIEWS' RETURN count(*) AS count")
    if not review_types or not review_types[0].get("count"):
        return []
    rows = run("""
        MATCH (v:ReviewEvent {decision:'accepted'})-[:REVIEWS]->(e:Evidence)-[:FROM_DOCUMENT]->(d:Document)
        WHERE v.reviewed_at >= $start AND v.reviewed_at < $end
          AND ($source IS NULL OR toLower(d.source_name) CONTAINS toLower($source))
        RETURN DISTINCT v.event_id AS event_id,v.reviewed_at AS reviewed_at,e.quote AS quote,e.relation_id AS relation_id,
               d.title AS title,d.url AS url,d.source_name AS source_name,d.published_at AS published_at
        ORDER BY v.reviewed_at DESC LIMIT 20
    """, start=datetime.combine(start, datetime.min.time(), tzinfo=VN_TZ).isoformat(), end=datetime.combine(end_exclusive, datetime.min.time(), tzinfo=VN_TZ).isoformat(), source=source)
    relations = _relation_lookup(list({row["relation_id"] for row in rows if row.get("relation_id")}))
    result = []
    for row in rows:
        relation = relations.get(row.get("relation_id"), {})
        result.append({**row, "relation": relation.get("relation_type"), "source": relation.get("source_entity"), "target": relation.get("target_entity")})
    return result


def _collection_coverage_days(start: date, end_exclusive: date) -> set[str]:
    """Read explicitly completed collection days; article presence is not a coverage signal."""
    path = RAW_DIR / "collection_coverage.jsonl"
    covered = set()
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    day = date.fromisoformat(row.get("date", ""))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
                if row.get("complete") is True and start <= day < end_exclusive:
                    covered.add(day.isoformat())
    except OSError:
        pass
    return covered


def _classification_rows() -> list[dict]:
    path = INTERIM_DIR / "document_classifications.csv"
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    except (OSError, csv.Error):
        return []


def _latest_classifications() -> dict[str, dict]:
    latest = {}
    for row in _classification_rows():
        if row.get("document_id"):
            latest[row["document_id"]] = row
    return latest


def _relation_lookup(relation_ids: list[str]) -> dict[str, dict]:
    """Resolve a batch of evidence relation IDs with one graph scan, not one scan per evidence row."""
    if not relation_ids:
        return {}
    rows = run("""
        MATCH (a:Entity)-[r]-(b:Entity)
        WHERE r.relation_id IN $ids
        RETURN r.relation_id AS relation_id,type(r) AS relation_type,
               startNode(r).entity_id AS source_entity_id,startNode(r).name AS source_entity,
               endNode(r).entity_id AS target_entity_id,endNode(r).name AS target_entity
    """, ids=relation_ids)
    return {row["relation_id"]: row for row in rows if row.get("relation_id")}


def _classification_status() -> dict:
    try:
        return json.loads((RAW_DIR / "content_classification_status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "not_configured"}


def _scheduler_status() -> dict:
    try:
        state = json.loads((RAW_DIR / "live_scheduler_status.json").read_text(encoding="utf-8"))
        heartbeat = datetime.fromisoformat(state["heartbeat_at"])
        age = (datetime.now(VN_TZ) - heartbeat.astimezone(VN_TZ)).total_seconds()
        if state.get("status") != "running":
            status = "not_running"
        else:
            status = "running" if 0 <= age <= 150 else "stale"
        return {**state, "status": status, "age_seconds": max(0, round(age))}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"status": "not_running", "next_runs": {}}


TOPIC_BY_RELATION = {
    "PERFORMED": "phát hành và tác phẩm", "FEATURED_ON": "hợp tác", "COMPOSED": "phát hành và tác phẩm",
    "PRODUCED": "phát hành và tác phẩm", "RELEASED_BY": "doanh nghiệp và thương hiệu", "TRACK_OF": "phát hành và tác phẩm",
    "COLLABORATED_WITH": "hợp tác", "DISPUTED_WITH": "tranh chấp", "PERFORMED_AT": "biểu diễn",
    "CONTESTANT_ON": "chương trình", "JUDGE_ON": "chương trình", "ORGANIZED_BY": "doanh nghiệp và thương hiệu",
    "AMBASSADOR_OF": "thương hiệu",
}


@app.get("/api/overview")
def overview(days: int = Query(7, ge=7, le=90), source: str | None = None) -> dict:
    """Tổng hợp trên toàn bộ chứng cứ trong kỳ; không bị giới hạn bởi số dòng của feed."""
    today = datetime.now(VN_TZ).date()
    start = today - timedelta(days=days - 1)
    previous_start = start - timedelta(days=days)
    today_exclusive = today + timedelta(days=1)
    evidence_rows = run("""
        MATCH (e:Evidence)-[:FROM_DOCUMENT]->(d:Document)
        WHERE d.published_at >= $previous_start AND d.published_at < $today_exclusive
          AND ($source IS NULL OR toLower(d.source_name) CONTAINS toLower($source))
        RETURN d.document_id AS document_id,d.title AS title,d.url AS url,d.published_at AS published_at,d.collected_at AS collected_at,
               d.platform AS platform,d.source_name AS source,e.relation_id AS relation_id,e.quote AS quote
        ORDER BY d.published_at DESC
    """, previous_start=previous_start.isoformat(), today_exclusive=today_exclusive.isoformat(), source=source)
    relation_map = _relation_lookup(list({row["relation_id"] for row in evidence_rows if row.get("relation_id")}))
    rows = [{**row, **relation_map.get(row.get("relation_id"), {})} for row in evidence_rows]
    periods = {"current": {}, "previous": {}}
    entities = {"current": {}, "previous": {}}
    relations = {"current": set(), "previous": set()}
    topics: dict[str, set[str]] = {}
    sentiments: dict[str, set[str]] = {}
    for row in rows:
        day = str(row.get("published_at") or "")[:10]
        if not _day_in_period(day, previous_start, today_exclusive):
            continue
        period = "current" if day >= start.isoformat() else "previous"
        doc_id = row.get("document_id")
        if doc_id:
            periods[period].setdefault(doc_id, {"day": day, "collected_at": row.get("collected_at"), "platform": row.get("platform")})
        for entity_id, name in ((row.get("source_entity_id"), row.get("source_entity")), (row.get("target_entity_id"), row.get("target_entity"))):
            if entity_id:
                entities[period].setdefault(entity_id, {"id": entity_id, "name": name})
        if row.get("relation_type") and doc_id:
            relations[period].add((doc_id, row["relation_type"], row.get("source_entity_id"), row.get("target_entity_id")))
        if period == "current" and doc_id:
            inferred_topics = set()
            if row.get("relation_type") in TOPIC_BY_RELATION:
                inferred_topics.add(TOPIC_BY_RELATION[row["relation_type"]])
            for topic in inferred_topics:
                topics.setdefault(str(topic), set()).add(doc_id)
    latest_classifications = _latest_classifications()
    for document_id in periods["current"]:
        classification = latest_classifications.get(document_id, {})
        if classification.get("status") != "ready":
            continue
        for topic in (classification.get("topics") or "").split("|"):
            if topic:
                topics.setdefault(topic, set()).add(document_id)
        if classification.get("sentiment"):
            sentiments.setdefault(classification["sentiment"], set()).add(document_id)
    platforms = Counter(item["platform"] or "unknown" for item in periods["current"].values())
    daily = Counter(item["day"] for item in periods["current"].values())
    entity_documents = {"current": {}, "previous": {}}
    for row in rows:
        day = str(row.get("published_at") or "")[:10]
        if not _day_in_period(day, previous_start, today_exclusive):
            continue
        period = "current" if day >= start.isoformat() else "previous"
        if row.get("document_id"):
            for entity_id in {row.get("source_entity_id"), row.get("target_entity_id")} - {None}:
                entity_documents[period].setdefault(entity_id, set()).add(row["document_id"])
    top_entities = []
    for entity_id, value in entities["current"].items():
        current_mentions = len(entity_documents["current"].get(entity_id, set()))
        previous_mentions = len(entity_documents["previous"].get(entity_id, set()))
        top_entities.append({"id": entity_id, **value, "documents": current_mentions, "previous_documents": previous_mentions, "delta": current_mentions - previous_mentions})
    top_entities = [row for row in top_entities if row["delta"] > 0]
    top_entities.sort(key=lambda row: (-row["delta"], -row["documents"], row["name"] or ""))
    top_entities = top_entities[:5]
    community_docs: dict[str, set[str]] = {}
    community_names: dict[str, str] = {}
    try:
        member_rows = table("community_members")
        overview_rows = table("communities")
        community_by_entity = {str(row.get("entity_id")): str(row.get("community")) for row in member_rows if row.get("entity_id") is not None and row.get("community") is not None}
        community_names = {str(row.get("community")): str(row.get("main_genre") or f"Cộng đồng {row.get('community')}") for row in overview_rows}
        community_sizes = {str(row.get("community")): int(float(row.get("size") or 0)) for row in overview_rows}
        for entity_id, docs in entity_documents["current"].items():
            community_id = community_by_entity.get(entity_id)
            if community_id:
                community_docs.setdefault(community_id, set()).update(docs)
    except (HTTPException, OSError, ValueError, TypeError):
        community_sizes = {}
    top_communities = sorted(({"id": cid, "name": community_names.get(cid, f"Cộng đồng {cid}"), "size": community_sizes.get(cid, 0), "documents": len(doc_ids)} for cid, doc_ids in community_docs.items()), key=lambda row: (-row["documents"], row["name"]))[:5]
    recent_by_id = {}
    for row in rows:
        if not row.get("document_id") or not _day_in_period(row.get("published_at"), start, today_exclusive) or not row.get("relation_type"):
            continue
        document = recent_by_id.setdefault(row["document_id"], {"document_id": row["document_id"], "title": row.get("title"), "url": row.get("url"), "source": row.get("source"), "published_at": row.get("published_at"), "platform": row.get("platform"), "relations": []})
        relation = {"relation": row["relation_type"], "relation_id": row.get("relation_id"), "source": row.get("source_entity"), "target": row.get("target_entity"), "evidence": row.get("quote")}
        if relation not in document["relations"]:
            document["relations"].append(relation)
    recent_documents = sorted(recent_by_id.values(), key=lambda row: (row.get("published_at") or "", row.get("document_id") or ""), reverse=True)[:5]
    approved_recent = _reviewed_relations_since(start, today_exclusive, source)
    current_count = len(periods["current"])
    previous_count = len(periods["previous"])
    freshness = run("MATCH (d:Document) RETURN max(d.collected_at) AS latest_collected_at,max(d.published_at) AS latest_published_at")
    latest_collected = freshness[0].get("latest_collected_at") if freshness else None
    latest_published = freshness[0].get("latest_published_at") if freshness else None
    current_coverage = _collection_coverage_days(start, today_exclusive)
    previous_coverage = _collection_coverage_days(previous_start, start)
    coverage_complete = len(current_coverage) == days and len(previous_coverage) == days
    manifest = ANALYSIS_DIR / "analysis_manifest.json"
    try:
        analysis_snapshot = json.loads(manifest.read_text(encoding="utf-8"))
        analysis_snapshot = {"graph_version": analysis_snapshot.get("graph_version"), "generated_at": analysis_snapshot.get("generated_at")}
    except (OSError, json.JSONDecodeError):
        analysis_snapshot = None
    return {
        "period": {"days": days, "from": start.isoformat(), "to": today.isoformat(), "previous_from": previous_start.isoformat(), "previous_to": (start - timedelta(days=1)).isoformat()},
        "generated_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
        "latest_collected_at": latest_collected or None,
        "latest_published_at": latest_published or None,
        "coverage": {"status": "complete" if coverage_complete else "incomplete", "current_days": len(current_coverage), "previous_days": len(previous_coverage), "days_per_period": days, "note": f"Độ phủ nhật ký: kỳ này {len(current_coverage)}/{days} ngày, kỳ trước {len(previous_coverage)}/{days} ngày. Ngày không có bài chỉ được tính đủ độ phủ nếu pipeline ghi nhận thu thập thành công."},
        "metrics": {"documents": _compare_period(current_count, previous_count, coverage_complete=coverage_complete), "entities": _compare_period(len(entities["current"]), len(entities["previous"]), coverage_complete=coverage_complete), "relations": _compare_period(len(relations["current"]), len(relations["previous"]), coverage_complete=coverage_complete)},
        "daily": [{"date": (start + timedelta(days=i)).isoformat(), "documents": daily.get((start + timedelta(days=i)).isoformat(), 0)} for i in range(days)],
        "top_entities": top_entities,
        "recent_documents": recent_documents,
        "platforms": [{"platform": key, "documents": value} for key, value in platforms.most_common()],
        "topics": {"status": "ready" if any(row.get("status") == "ready" for row in latest_classifications.values()) else "relation_derived" if topics else _classification_status().get("status", "not_available"), "items": [{"topic": key, "documents": len(value)} for key, value in sorted(topics.items(), key=lambda item: (-len(item[1]), item[0]))]},
        "top_communities": top_communities,
        "analysis_snapshot": analysis_snapshot,
        "sentiment": {"status": "ready" if sentiments else _classification_status().get("status", "not_available"), "interpretation": "Phân loại nội dung nguồn; không đại diện cảm xúc công chúng.", "items": [{"sentiment": key, "documents": len(value)} for key, value in sorted(sentiments.items(), key=lambda item: (-len(item[1]), item[0]))]},
        "new_relations": approved_recent,
        "source_document_limit": None,
    }


@app.get("/api/rankings")
def rankings(measure: str = "pagerank", role: str | None = None, limit: int = Query(30, le=200), graph_version: str | None = None) -> list[dict]:
    rows = pd.DataFrame(table("artist_metrics", graph_version))
    if measure not in {"pagerank", "degree", "strength", "betweenness", "eigenvector"}:
        raise HTTPException(400, "measure không hợp lệ")
    if role:
        rows = rows[rows.main_role == role]
    cols = ["entity_id", "name", "entity_type", "main_role", "genre_group", "community", "core", "degree", "pagerank", "betweenness", "eigenvector"]
    top = rows.nlargest(limit, measure)[cols]
    return top.astype(object).where(top.notna(), None).to_dict("records")


@app.get("/api/communities")
def communities(graph_version: str | None = None) -> list[dict]:
    selected = graph_version
    if selected is None:
        manifest = ANALYSIS_DIR / "analysis_manifest.json"
        if manifest.exists():
            selected = json.loads(manifest.read_text(encoding="utf-8")).get("graph_version")
    cores = {c["community"]: c for c in table("community_cores", graph_version)}
    summaries = {}
    if selected:
        for row in run("MATCH (s:CommunitySummary {graph_version:$version}) RETURN toInteger(s.community_id) AS community_id,s.summary AS summary,s.source_ids AS source_ids ORDER BY s.updated_at", version=selected):
            if row.get("community_id") is not None:
                summaries[int(row["community_id"])] = row
    all_source_ids = sorted({sid for row in summaries.values() for sid in (row.get("source_ids") or [])})
    source_rows = run("MATCH (e:Evidence)-[:FROM_DOCUMENT]->(d:Document) WHERE e.evidence_id IN $ids RETURN e.evidence_id AS source_id,d.title AS title,d.url AS url,d.source_name AS source,d.published_at AS published_at", ids=all_source_ids) if all_source_ids else []
    source_map = {row["source_id"]: row for row in source_rows}
    output = []
    for community in table("communities", graph_version):
        cid = int(community["community"])
        summary = summaries.get(cid, {})
        output.append({**community, **{k: v for k, v in cores.get(community["community"], {}).items() if k != "size"}, "summary": summary.get("summary"), "summary_sources": [source_map[sid] for sid in summary.get("source_ids", []) if sid in source_map]})
    return output


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(15, le=50)) -> list[dict]:
    return run(
        """
        MATCH (n:Entity)
        WHERE toLower(n.name) CONTAINS toLower($q) OR any(a IN coalesce(n.aliases, []) WHERE toLower(a) CONTAINS toLower($q))
        WITH n, COUNT { (n)--(:Entity) } AS degree
        RETURN n.entity_id AS id, n.name AS name, [l IN labels(n) WHERE l <> 'Entity'][0] AS type, degree, n.pagerank AS pagerank
        ORDER BY (toLower(n.name) = toLower($q)) DESC, coalesce(n.pagerank, 0) DESC, degree DESC
        LIMIT $limit
        """,
        q=q, limit=limit,
    )


ENTITY_FIELDS = "n.entity_id AS id, n.name AS name, [l IN labels(n) WHERE l <> 'Entity'][0] AS type"


@app.get("/api/entity/{entity_id}")
def entity(entity_id: str, limit: int = Query(60, le=300)) -> dict:
    found = run(f"MATCH (n:Entity {{entity_id: $id}}) RETURN {ENTITY_FIELDS}, properties(n) AS props", id=entity_id)
    if not found:
        raise HTTPException(404, "Không có thực thể này")
    neighbors = run(
        """
        MATCH (n:Entity {entity_id: $id})-[r]-(m:Entity)
        RETURN m.entity_id AS id, m.name AS name, [l IN labels(m) WHERE l <> 'Entity'][0] AS type, type(r) AS relation,
               startNode(r) = n AS outgoing, r.relation_id AS relation_id, r.n_documents AS n_documents, r.first_year AS first_year,
               r.weight AS weight, m.pagerank AS pagerank, m.community AS community
        ORDER BY coalesce(m.pagerank, 0) DESC, coalesce(r.n_documents, 0) DESC
        LIMIT $limit
        """,
        id=entity_id, limit=limit,
    )
    counts = run("MATCH (n:Entity {entity_id: $id})-[r]-(:Entity) RETURN type(r) AS relation, count(*) AS n ORDER BY n DESC", id=entity_id)
    return {**found[0], "neighbors": neighbors, "relation_counts": counts}


@app.get("/api/evidence/{relation_id}")
def evidence(relation_id: str, limit: int = Query(10, le=50)) -> list[dict]:
    return run(
        """
        MATCH (e:Evidence {relation_id: $rid})-[:FROM_DOCUMENT]->(d:Document)
        RETURN e.quote AS quote, e.sentence_location AS location, e.extraction_method AS method, e.confidence_score AS confidence,
               d.title AS title, d.url AS url, d.source_name AS source, d.platform AS platform, d.published_at AS published_at
        ORDER BY d.published_at DESC LIMIT $limit
        """,
        rid=relation_id, limit=limit,
    )


@app.get("/api/path")
def path(source: str, target: str, max_hops: int = Query(3, ge=1, le=3)) -> dict:
    """Đường đi ngắn nhất giữa hai thực thể, mỗi bước kèm một câu bằng chứng (nền của màn hình Vì sao liên quan)."""
    rows = run(
        f"""
        MATCH (a:Entity {{entity_id: $s}}), (b:Entity {{entity_id: $t}})
        MATCH p = (a)-[:{'|'.join(sorted(RELATION_SIGNATURES))}*1..{max_hops}]-(b)
        WHERE all(r IN relationships(p) WHERE type(r) IN $types AND EXISTS {{
            MATCH (ev:Evidence {{relation_id:r.relation_id}})-[:FROM_DOCUMENT]->(:Document)
        }})
        WITH p ORDER BY length(p), reduce(score=0.0,n IN nodes(p) | score + coalesce(n.pagerank,0.0)) DESC LIMIT 1
        RETURN [n IN nodes(p) | {{id: n.entity_id, name: n.name, type: [l IN labels(n) WHERE l <> 'Entity'][0]}}] AS nodes,
               [r IN relationships(p) | {{relation: type(r), relation_id: r.relation_id, source: startNode(r).entity_id, target: endNode(r).entity_id}}] AS edges
        """,
        s=source, t=target, types=sorted(RELATION_SIGNATURES),
    )
    if not rows:
        return {"found": False, "nodes": [], "edges": []}
    edges = rows[0]["edges"]
    quotes = run(
        """
        UNWIND $ids AS rid
        CALL (rid) { MATCH (e:Evidence {relation_id: rid})-[:FROM_DOCUMENT]->(d:Document) RETURN e.quote AS quote, d.url AS url, d.source_name AS src ORDER BY d.published_at DESC LIMIT 1 }
        RETURN rid, quote, url, src
        """,
        ids=[e["relation_id"] for e in edges],
    )
    by_id = {q["rid"]: q for q in quotes}
    for e in edges:
        q = by_id.get(e["relation_id"], {})
        e.update(quote=q.get("quote"), url=q.get("url"), source_name=q.get("src"))
    return {"found": True, "hops": len(edges), "nodes": rows[0]["nodes"], "edges": edges}


class WatchRequest(BaseModel):
    entity_id: str


class AskRequest(BaseModel):
    question: str = Field(min_length=4, max_length=1200)
    method: str = "graph"
    max_hops: int = Field(default=3, ge=1, le=3)
    relation_types: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None


class ExplainRequest(BaseModel):
    source: str
    target: str
    max_hops: int = Field(default=3, ge=1, le=3)
    relation_types: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None


def _validate_dates(date_from: str | None, date_to: str | None) -> None:
    try:
        if date_from:
            date.fromisoformat(date_from)
        if date_to:
            date.fromisoformat(date_to)
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from phải trước hoặc bằng date_to")
    except ValueError as exc:
        raise HTTPException(400, f"Ngày lọc không hợp lệ: {exc}") from exc


def _alert_stats(baseline: dict[str, int], current_documents: list[dict], history_complete: bool) -> dict:
    daily_counts = [int(value) for value in baseline.values()]
    average = mean(daily_counts) if daily_counts else 0.0
    deviation = pstdev(daily_counts) if daily_counts else 0.0
    unique = {}
    for row in current_documents:
        if row.get("document_id"):
            unique.setdefault(row["document_id"], row)
    count = len(unique)
    score = ((count / 7) - average) / deviation if deviation else None
    enough_history = history_complete and deviation > 0
    return {
        "count_7d": count,
        "baseline_daily_mean": round(average, 3),
        "z_score": round(score, 3) if score is not None else None,
        "anomaly": bool(enough_history and score is not None and score >= 2),
        "requires_more_history": not enough_history,
        "current_documents": list(unique.values()),
    }


def _trend_stats(rows: list[dict], days: int) -> dict:
    daily: Counter[str] = Counter()
    entity_documents: dict[str, set[str]] = {}
    entity_names: dict[str, str] = {}
    documents = {}
    for row in rows:
        document_id = row.get("document_id")
        key = str(row.get("day") or "")[:10]
        if not document_id or not key:
            continue
        documents.setdefault(document_id, key)
        for value in row.get("entities") or []:
            entity_id = value.get("id") if isinstance(value, dict) else str(value)
            name = value.get("name") if isinstance(value, dict) else str(value)
            if entity_id:
                entity_id = str(entity_id)
                entity_documents.setdefault(entity_id, set()).add(str(document_id))
                entity_names[entity_id] = str(name or entity_id)
    for day in documents.values():
        daily[day] += 1
    top_entities = [{"id": key, "name": entity_names[key], "documents": len(doc_ids)} for key, doc_ids in entity_documents.items()]
    top_entities.sort(key=lambda item: (-item["documents"], item["name"]))
    return {"days": days, "daily": [{"date": key, "documents": value} for key, value in sorted(daily.items())], "top_entities": top_entities[:20], "total_documents": len(documents)}


@app.get("/api/feed")
def feed(entity_id: str | None = None, source: str | None = None, date_from: str | None = None, date_to: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> list[dict]:
    _validate_dates(date_from, date_to)
    return run("""
        MATCH (a:Entity)-[r]-(b:Entity)
        WHERE ($entity_id IS NULL OR a.entity_id=$entity_id OR b.entity_id=$entity_id)
        MATCH (e:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
        WHERE ($date_from IS NULL OR d.published_at >= $date_from) AND ($date_to IS NULL OR d.published_at <= $date_to)
          AND ($source IS NULL OR toLower(d.source_name) CONTAINS toLower($source))
        WITH d, collect(DISTINCT {relation:type(r), relation_id:r.relation_id, source:startNode(r).name, target:endNode(r).name, evidence:e.quote}) AS relations
        RETURN d.document_id AS document_id, d.title AS title, d.url AS url, d.source_name AS source,
               d.published_at AS published_at,d.collected_at AS collected_at, d.platform AS platform, relations
        ORDER BY d.published_at DESC, d.document_id SKIP $offset LIMIT $limit
    """, entity_id=entity_id, source=source, date_from=date_from, date_to=date_to, offset=offset, limit=limit)


@app.get("/api/watchlists")
def get_watchlists() -> list[dict]:
    watch_types = run("CALL db.relationshipTypes() YIELD relationshipType WHERE relationshipType='WATCHES' RETURN count(*) AS count")
    if not watch_types or not watch_types[0].get("count"):
        return []
    return run("""
        MATCH (:LocalWatchlist {owner:'local'})-[:WATCHES]->(n:Entity)
        RETURN n.entity_id AS entity_id,n.name AS name,[l IN labels(n) WHERE l<>'Entity'][0] AS type,n.pagerank AS pagerank
        ORDER BY n.name
    """)


@app.post("/api/watchlists", status_code=201)
def add_watchlist(body: WatchRequest) -> dict:
    result = run("""
        MATCH (n:Entity {entity_id:$id})
        MERGE (w:LocalWatchlist {owner:'local'})
        MERGE (w)-[:WATCHES]->(n)
        RETURN n.entity_id AS entity_id,n.name AS name,[l IN labels(n) WHERE l<>'Entity'][0] AS type
    """, id=body.entity_id)
    if not result:
        raise HTTPException(404, "Không có thực thể này")
    return result[0]


@app.delete("/api/watchlists/{entity_id}", status_code=204)
def remove_watchlist(entity_id: str) -> None:
    run("MATCH (:LocalWatchlist {owner:'local'})-[r:WATCHES]->(n:Entity {entity_id:$id}) DELETE r", id=entity_id)


@app.get("/api/alerts")
def alerts(scope_steps: int = Query(1, ge=1, le=2), event_types: list[str] | None = Query(None)) -> list[dict]:
    watched = get_watchlists()
    today = datetime.now(VN_TZ).date()
    current_start = today - timedelta(days=6)
    baseline_start = current_start - timedelta(days=28)
    end_exclusive = today + timedelta(days=1)
    baseline_days = {(baseline_start + timedelta(days=i)).isoformat() for i in range(28)}
    covered_days = _collection_coverage_days(baseline_start, current_start)
    history_complete = baseline_days.issubset(covered_days)
    alerts_out = []
    for entity_row in watched:
        rows = run("""
            MATCH p=(n:Entity {entity_id:$id})-[*1..""" + str(scope_steps) + """]-(m:Entity)
            UNWIND range(0,size(relationships(p))-1) AS edge_index
            WITH n, nodes(p)[edge_index+1] AS m, relationships(p)[edge_index] AS r, edge_index+1 AS distance
            MATCH (e:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
            WHERE d.published_at >= $since AND d.published_at < $until
              AND ($event_types IS NULL OR any(kind IN $event_types WHERE
                (kind='collaboration' AND type(r) IN ['COLLABORATED_WITH','FEATURED_ON']) OR
                (kind='release' AND type(r) IN ['PERFORMED','COMPOSED','PRODUCED','TRACK_OF','RELEASED_BY']) OR
                (kind='dispute' AND type(r)='DISPUTED_WITH') OR
                (kind='show' AND type(r) IN ['PERFORMED_AT','CONTESTANT_ON','JUDGE_ON']) OR
                (kind='new_mentions' AND type(r) NOT IN ['COLLABORATED_WITH','FEATURED_ON','PERFORMED','COMPOSED','PRODUCED','TRACK_OF','RELEASED_BY','DISPUTED_WITH','PERFORMED_AT','CONTESTANT_ON','JUDGE_ON'])))
            WITH d,collect(DISTINCT {evidence_id:e.evidence_id,title:d.title,url:d.url,source:d.source_name,published_at:d.published_at,relation:type(r),related_name:m.name,distance:distance,path:[node IN nodes(p) | node.name],quote:e.quote}) AS items
            RETURN d.published_at AS day,d.document_id AS document_id,items
        """, id=entity_row["entity_id"], since=baseline_start.isoformat(), until=end_exclusive.isoformat(), event_types=event_types)
        daily = { (baseline_start + timedelta(days=i)).isoformat(): 0 for i in range(28) }
        current = {}
        seen_docs = set()
        for row in rows:
            day = str(row.get("day") or "")[:10]
            doc_id = row.get("document_id")
            if not doc_id or doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)
            if day in daily:
                daily[day] += 1
            elif current_start.isoformat() <= day < end_exclusive.isoformat():
                current[doc_id] = row
        stats = _alert_stats(daily, list(current.values()), history_complete)
        if stats["count_7d"]:
            source_map = {}
            for row in stats.pop("current_documents"):
                for source in row.get("items") or []:
                    if source.get("evidence_id"):
                        source_map.setdefault(source["evidence_id"], source)
            relation_types = {source.get("relation") for source in source_map.values()}
            if relation_types & {"DISPUTED_WITH"}:
                kind = "dispute"
            elif relation_types & {"COLLABORATED_WITH", "FEATURED_ON"}:
                kind = "collaboration"
            elif relation_types & {"PERFORMED", "COMPOSED", "PRODUCED", "TRACK_OF", "RELEASED_BY"}:
                kind = "release"
            elif relation_types & {"PERFORMED_AT", "CONTESTANT_ON", "JUDGE_ON"}:
                kind = "show"
            else:
                kind = "new_mentions"
            alerts_out.append({"entity_id": entity_row["entity_id"], "name": entity_row["name"], "kind": kind, "scope_steps": scope_steps, **stats, "sources": list(source_map.values())[:5]})
    return alerts_out


@app.get("/api/trends")
def trends(days: int = Query(30, ge=1, le=365), entity_id: str | None = None, source: str | None = None, community_id: str | None = None, topic: str | None = None, sentiment: str | None = None) -> dict:
    today = datetime.now(VN_TZ).date()
    current_start = today - timedelta(days=days - 1)
    previous_start = current_start - timedelta(days=days)
    end_exclusive = today + timedelta(days=1)
    evidence_rows = run("""
        MATCH (e:Evidence)-[:FROM_DOCUMENT]->(d:Document)
        WHERE d.published_at >= $since AND d.published_at < $until
          AND ($source IS NULL OR toLower(d.source_name) CONTAINS toLower($source))
        RETURN d.published_at AS day,d.document_id AS document_id,d.source_name AS source,e.relation_id AS relation_id
        ORDER BY day
    """, since=previous_start.isoformat(), until=end_exclusive.isoformat(), source=source)
    relation_map = _relation_lookup(list({row["relation_id"] for row in evidence_rows if row.get("relation_id")}))
    grouped_rows = {}
    for row in evidence_rows:
        document_id = row.get("document_id")
        if not document_id:
            continue
        grouped = grouped_rows.setdefault(document_id, {**row, "entities_by_id": {}, "relation_types_set": set()})
        relation = relation_map.get(row.get("relation_id"), {})
        if relation.get("relation_type"):
            grouped["relation_types_set"].add(relation["relation_type"])
        for entity_key, name_key in (("source_entity_id", "source_entity"), ("target_entity_id", "target_entity")):
            entity_key_value = relation.get(entity_key)
            if entity_key_value:
                grouped["entities_by_id"][str(entity_key_value)] = {"id": str(entity_key_value), "name": relation.get(name_key)}
    rows = []
    for grouped in grouped_rows.values():
        entities = list(grouped["entities_by_id"].values())
        if entity_id and not any(entity["id"] == entity_id for entity in entities):
            continue
        rows.append({**grouped, "entities": entities, "relation_types": sorted(grouped["relation_types_set"])})
    latest_classifications = _latest_classifications()
    scoped = rows
    if community_id:
        try:
            member_map = {str(row.get("entity_id")): str(row.get("community")) for row in table("community_members")}
            scoped = [row for row in rows if any(member_map.get(str(entity.get("id"))) == str(community_id) for entity in row.get("entities", []))]
        except HTTPException:
            scoped = []
    if topic or sentiment:
        selected_rows = []
        for row in scoped:
            classification = latest_classifications.get(row.get("document_id"), {})
            classified_topics = set((classification.get("topics") or "").split("|")) if classification.get("status") == "ready" else set()
            relation_topics = {TOPIC_BY_RELATION[relation_type] for relation_type in row.get("relation_types") or [] if relation_type in TOPIC_BY_RELATION}
            if topic and topic not in classified_topics | relation_topics:
                continue
            row_sentiment = classification.get("sentiment") if classification.get("status") == "ready" else None
            if sentiment and row_sentiment != sentiment:
                continue
            selected_rows.append(row)
        scoped = selected_rows
    current_rows = [row for row in scoped if _day_in_period(row.get("day"), current_start, end_exclusive)]
    previous_rows = [row for row in scoped if _day_in_period(row.get("day"), previous_start, current_start)]
    current = _trend_stats(current_rows, days)
    previous = _trend_stats(previous_rows, days)
    topic_docs: dict[str, set[str]] = {}
    community_docs: dict[str, set[str]] = {}
    sentiment_docs: dict[str, set[str]] = {}
    try:
        members = table("community_members")
        community_map = {str(row.get("entity_id")): str(row.get("community")) for row in members if row.get("entity_id") is not None and row.get("community") is not None}
        community_rows = table("communities")
        community_name = {str(row.get("community")): str(row.get("main_genre") or f"Cộng đồng {row.get('community')}") for row in community_rows}
        community_size = {str(row.get("community")): int(float(row.get("size") or 0)) for row in community_rows}
    except (HTTPException, ValueError, TypeError):
        community_map, community_name, community_size = {}, {}, {}
    for row in current_rows:
        doc_id = str(row.get("document_id") or "")
        if not doc_id:
            continue
        for relation_type in row.get("relation_types") or []:
            label = TOPIC_BY_RELATION.get(relation_type)
            if label:
                topic_docs.setdefault(label, set()).add(doc_id)
        classification = latest_classifications.get(doc_id, {})
        if classification.get("status") == "ready":
            for label in (classification.get("topics") or "").split("|"):
                if label:
                    topic_docs.setdefault(label, set()).add(doc_id)
        sentiment_value = classification.get("sentiment") if classification.get("status") == "ready" else None
        if sentiment_value:
            sentiment_docs.setdefault(sentiment_value, set()).add(doc_id)
        for entity in row.get("entities") or []:
            cid = community_map.get(str(entity.get("id")))
            if cid:
                community_docs.setdefault(cid, set()).add(doc_id)
    top_communities = [{"id": cid, "name": community_name.get(cid, f"Cộng đồng {cid}"), "size": community_size.get(cid, 0), "documents": len(docs)} for cid, docs in community_docs.items()]
    top_communities.sort(key=lambda item: (-item["documents"], item["name"]))
    current_coverage = _collection_coverage_days(current_start, end_exclusive)
    previous_coverage = _collection_coverage_days(previous_start, current_start)
    coverage_complete = len(current_coverage) == days and len(previous_coverage) == days
    result = {**current, "period": {"from": current_start.isoformat(), "previous_from": previous_start.isoformat(), "to": today.isoformat()}, "comparison": _compare_period(current["total_documents"], previous["total_documents"], coverage_complete=coverage_complete), "previous_daily": previous["daily"], "top_communities": top_communities[:20], "topics": [{"topic": label, "documents": len(ids)} for label, ids in sorted(topic_docs.items(), key=lambda item: (-len(item[1]), item[0]))], "sentiment": [{"sentiment": label, "documents": len(ids)} for label, ids in sorted(sentiment_docs.items(), key=lambda item: (-len(item[1]), item[0]))], "classification_status": _classification_status(), "filters": {"entity_id": entity_id, "community_id": community_id, "topic": topic, "sentiment": sentiment, "source": source}, "coverage": {"status": "complete" if coverage_complete else "incomplete", "current_days": len(current_coverage), "previous_days": len(previous_coverage)}}
    return result


@app.post("/api/explain")
def explain(body: ExplainRequest) -> dict:
    _validate_dates(body.date_from, body.date_to)
    allowed = body.relation_types or sorted(RELATION_SIGNATURES)
    if any(r not in RELATION_SIGNATURES for r in allowed):
        raise HTTPException(400, "relation_types có giá trị không hợp lệ")
    max_hops = min(body.max_hops, 3)
    rows = run(f"""
        MATCH (a:Entity {{entity_id:$source}}),(b:Entity {{entity_id:$target}})
        MATCH p=(a)-[:{'|'.join(sorted(allowed))}*1..{max_hops}]-(b)
        WHERE all(r IN relationships(p) WHERE type(r) IN $types AND EXISTS {{
            MATCH (ev:Evidence {{relation_id:r.relation_id}})-[:FROM_DOCUMENT]->(d:Document)
            WHERE ($date_from IS NULL OR d.published_at >= $date_from) AND ($date_to IS NULL OR d.published_at <= $date_to)
        }})
        WITH p ORDER BY length(p), reduce(score=0.0,n IN nodes(p) | score + coalesce(n.pagerank,0.0)) DESC LIMIT 1
        RETURN [n IN nodes(p) | {{id:n.entity_id,name:n.name,type:[l IN labels(n) WHERE l<>'Entity'][0]}}] AS nodes,
               [r IN relationships(p) | {{relation:type(r),relation_id:r.relation_id,source:startNode(r).entity_id,target:endNode(r).entity_id}}] AS edges
    """, source=body.source, target=body.target, types=allowed, date_from=body.date_from, date_to=body.date_to)
    if not rows:
        return {"found": False, "nodes": [], "edges": []}
    edge_rows = rows[0]["edges"]
    sources = run("""
        UNWIND $ids AS rid MATCH (e:Evidence {relation_id:rid})-[:FROM_DOCUMENT]->(d:Document)
        WHERE ($date_from IS NULL OR d.published_at >= $date_from) AND ($date_to IS NULL OR d.published_at <= $date_to)
        RETURN rid AS relation_id,e.quote AS quote,d.url AS url,d.title AS title,d.source_name AS source,d.published_at AS published_at
        ORDER BY d.published_at DESC
    """, ids=[e["relation_id"] for e in edge_rows], date_from=body.date_from, date_to=body.date_to)
    by_rel = {}
    for item in sources:
        by_rel.setdefault(item["relation_id"], []).append(item)
    for edge in edge_rows:
        edge["evidence"] = by_rel.get(edge["relation_id"], [])[:3]
    return {"found": True, "hops": len(edge_rows), "nodes": rows[0]["nodes"], "edges": edge_rows}


@app.post("/api/ask")
def ask(body: AskRequest) -> dict:
    _validate_dates(body.date_from, body.date_to)
    if body.method not in {"graph", "vector"}:
        raise HTTPException(400, "method phải là graph hoặc vector")
    if body.relation_types and any(r not in RELATION_SIGNATURES for r in body.relation_types):
        raise HTTPException(400, "relation_types có giá trị không hợp lệ")
    with DRIVER["neo4j"].session() as session:
        if body.method == "graph":
            evidence_bundle = retrieval.retrieve_graph(session, body.question, body.max_hops, body.relation_types, body.date_from, body.date_to)
        else:
            evidence_bundle = retrieval.retrieve_vector(session, body.question, date_from=body.date_from, date_to=body.date_to)
    return retrieval.answer(body.question, evidence_bundle, body.method)
