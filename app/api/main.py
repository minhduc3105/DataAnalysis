from contextlib import asynccontextmanager
from functools import lru_cache

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from crawler.analysis import OUT as ANALYSIS_DIR
from crawler.graphdb import connect

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


@lru_cache(maxsize=None)
def _table(name: str, mtime: float) -> list[dict]:
    df = pd.read_csv(ANALYSIS_DIR / f"{name}.csv", encoding="utf-8-sig")
    return df.astype(object).where(df.notna(), None).to_dict("records")


def table(name: str) -> list[dict]:
    path = ANALYSIS_DIR / f"{name}.csv"
    if not path.exists():
        raise HTTPException(503, f"Chưa có {path.name}; chạy `uv run python main.py analyze` trước")
    return _table(name, path.stat().st_mtime)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "entities": run("MATCH (n:Entity) RETURN count(n) AS n")[0]["n"]}


@app.get("/api/network")
def network() -> dict:
    """Số liệu phân tích mạng cho trang Chân dung mạng (kết quả của lệnh analyze)."""
    return {
        name: table(name)
        for name in [
            "overview", "collab_summary", "small_world", "distance_distribution", "small_world_paths", "community_methods",
            "kcore_distribution", "centrality_correlation", "top20_overlap", "pagerank_by_period", "relations_by_type", "nodes_by_type",
        ]
    }


@app.get("/api/rankings")
def rankings(measure: str = "pagerank", role: str | None = None, limit: int = Query(30, le=200)) -> list[dict]:
    rows = pd.DataFrame(table("artist_metrics"))
    if measure not in {"pagerank", "degree", "strength", "betweenness", "eigenvector"}:
        raise HTTPException(400, "measure không hợp lệ")
    if role:
        rows = rows[rows.main_role == role]
    cols = ["entity_id", "name", "entity_type", "main_role", "genre_group", "community", "core", "degree", "pagerank", "betweenness", "eigenvector"]
    top = rows.nlargest(limit, measure)[cols]
    return top.astype(object).where(top.notna(), None).to_dict("records")


@app.get("/api/communities")
def communities() -> list[dict]:
    cores = {c["community"]: c for c in table("community_cores")}
    return [{**c, **{k: v for k, v in cores.get(c["community"], {}).items() if k != "size"}} for c in table("communities")]


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
def path(source: str, target: str, max_hops: int = Query(4, ge=1, le=6)) -> dict:
    """Đường đi ngắn nhất giữa hai thực thể, mỗi bước kèm một câu bằng chứng (nền của màn hình Vì sao liên quan)."""
    rows = run(
        f"""
        MATCH (a:Entity {{entity_id: $s}}), (b:Entity {{entity_id: $t}})
        MATCH p = shortestPath((a)-[*..{max_hops}]-(b))
        RETURN [n IN nodes(p) | {{id: n.entity_id, name: n.name, type: [l IN labels(n) WHERE l <> 'Entity'][0]}}] AS nodes,
               [r IN relationships(p) | {{relation: type(r), relation_id: r.relation_id, source: startNode(r).entity_id, target: endNode(r).entity_id}}] AS edges
        """,
        s=source, t=target,
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
