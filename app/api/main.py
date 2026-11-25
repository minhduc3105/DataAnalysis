from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from functools import lru_cache
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
from crawler.config import VN_TZ

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
    daily = {}
    entity_counts = {}
    seen_documents = set()
    for row in rows:
        document_id = row.get("document_id")
        key = str(row.get("day") or "")[:10]
        if not document_id or not key or document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        daily[key] = daily.get(key, 0) + 1
        for name in set(row.get("entities") or []):
            if name:
                entity_counts[name] = entity_counts.get(name, 0) + 1
    return {"days": days, "daily": [{"date": k, "documents": v} for k, v in sorted(daily.items())], "top_entities": [{"name": k, "documents": v} for k, v in sorted(entity_counts.items(), key=lambda x: -x[1])[:20]], "total_documents": sum(daily.values())}


@app.get("/api/feed")
def feed(entity_id: str | None = None, source: str | None = None, date_from: str | None = None, date_to: str | None = None, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    _validate_dates(date_from, date_to)
    return run("""
        MATCH (a:Entity)-[r]-(b:Entity)
        WHERE ($entity_id IS NULL OR a.entity_id=$entity_id OR b.entity_id=$entity_id)
        MATCH (e:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
        WHERE ($date_from IS NULL OR d.published_at >= $date_from) AND ($date_to IS NULL OR d.published_at <= $date_to)
          AND ($source IS NULL OR toLower(d.source_name) CONTAINS toLower($source))
        WITH d, collect(DISTINCT {relation:type(r), relation_id:r.relation_id, source:startNode(r).name, target:endNode(r).name, evidence:e.quote}) AS relations
        RETURN d.document_id AS document_id, d.title AS title, d.url AS url, d.source_name AS source,
               d.published_at AS published_at, d.platform AS platform, relations
        ORDER BY d.published_at DESC LIMIT $limit
    """, entity_id=entity_id, source=source, date_from=date_from, date_to=date_to, limit=limit)


@app.get("/api/watchlists")
def get_watchlists() -> list[dict]:
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
def alerts() -> list[dict]:
    watched = get_watchlists()
    today = datetime.now(VN_TZ).date()
    current_start = today - timedelta(days=6)
    baseline_start = current_start - timedelta(days=28)
    baseline_days = {(baseline_start + timedelta(days=i)).isoformat() for i in range(28)}
    coverage_rows = run("""
        MATCH (:Evidence)-[:FROM_DOCUMENT]->(d:Document)
        WHERE d.published_at >= $start AND d.published_at < $end
        RETURN collect(DISTINCT substring(d.published_at,0,10)) AS dates
    """, start=baseline_start.isoformat(), end=current_start.isoformat())
    covered_days = set((coverage_rows[0].get("dates") or []) if coverage_rows else [])
    history_complete = baseline_days.issubset(covered_days)
    alerts_out = []
    for entity_row in watched:
        rows = run("""
            MATCH (n:Entity {entity_id:$id})-[r]-(m:Entity)
            MATCH (e:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
            WHERE d.published_at >= $since
            WITH d,collect(DISTINCT {evidence_id:e.evidence_id,title:d.title,url:d.url,source:d.source_name,relation:type(r),related_name:m.name}) AS items
            RETURN d.published_at AS day,d.document_id AS document_id,items
        """, id=entity_row["entity_id"], since=baseline_start.isoformat())
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
            elif day >= current_start.isoformat():
                current[doc_id] = row
        stats = _alert_stats(daily, list(current.values()), history_complete)
        if stats["count_7d"]:
            source_map = {}
            for row in stats.pop("current_documents"):
                for source in row.get("items") or []:
                    if source.get("evidence_id"):
                        source_map.setdefault(source["evidence_id"], source)
            alerts_out.append({"entity_id": entity_row["entity_id"], "name": entity_row["name"], "kind": "new_mentions", **stats, "sources": list(source_map.values())[:5]})
    return alerts_out


@app.get("/api/trends")
def trends(days: int = Query(30, ge=1, le=365), entity_id: str | None = None, source: str | None = None) -> dict:
    since = (datetime.now(VN_TZ).date() - timedelta(days=days - 1)).isoformat()
    rows = run("""
        MATCH (e:Evidence)-[:FROM_DOCUMENT]->(d:Document)
        WHERE d.published_at >= $since AND ($source IS NULL OR toLower(d.source_name) CONTAINS toLower($source))
        OPTIONAL MATCH (a:Entity)-[r]-(b:Entity) WHERE r.relation_id=e.relation_id AND ($entity_id IS NULL OR a.entity_id=$entity_id OR b.entity_id=$entity_id)
        WITH d, collect(DISTINCT coalesce(a.name,b.name)) AS entities
        WHERE $entity_id IS NULL OR size(entities)>0
        RETURN d.published_at AS day,d.document_id AS document_id,d.source_name AS source,entities
        ORDER BY day
    """, since=since, source=source, entity_id=entity_id)
    return _trend_stats(rows, days)


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
