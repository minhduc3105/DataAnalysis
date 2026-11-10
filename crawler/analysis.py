import pandas as pd

from .config import INTERIM_DIR
from .graphdb import connect

OUT = INTERIM_DIR / "analysis"
COLLAB = "collab"
PERIODS = [(2016, 2018), (2019, 2021), (2022, 2024), (2025, 2026)]
TOP = 30
METRIC_PROPS = ["community", "pagerank", "betweenness", "collab_degree", "collab_strength", "component"]

# Mạng hợp tác (Bước 12.2): nút nghệ sĩ/nhóm, cạnh COLLABORATED_WITH vô hướng, trọng số = số bài chung.
PROJECT_COLLAB = """
MATCH (a:Entity)-[r:COLLABORATED_WITH]->(b:Entity)
WHERE (a:Person OR a:Group) AND (b:Person OR b:Group)
  AND ($include_show OR NOT coalesce(r.show_only, false))
  AND r.first_year >= $y0 AND r.first_year <= $y1
WITH gds.graph.project($name, a, b, {relationshipProperties: r {.weight}}, {undirectedRelationshipTypes: ['*']}) AS g
RETURN g.nodeCount AS nodes, g.relationshipCount / 2 AS edges
"""

PROJECT_FULL = """
MATCH (a:Entity)
OPTIONAL MATCH (a)-[r]->(b:Entity)
WITH gds.graph.project($name, a, b, {}, {undirectedRelationshipTypes: ['*']}) AS g
RETURN g.nodeCount AS nodes, g.relationshipCount / 2 AS edges
"""


def _df(session, query: str, **params) -> pd.DataFrame:
    return pd.DataFrame([r.data() for r in session.run(query, **params)])


def _one(session, query: str, **params) -> dict:
    return session.run(query, **params).single().data()


def _drop(session, name: str) -> None:
    session.run("CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName", name=name).consume()


def _save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, encoding="utf-8-sig")
    print(f"  → {name} ({len(df)} dòng)")


def _network_stats(session, name: str, nodes: int, edges: int) -> dict:
    wcc = _one(session, "CALL gds.wcc.stats($name) YIELD componentCount, componentDistribution RETURN componentCount AS c, componentDistribution.max AS m", name=name)
    lv = _one(session, "CALL gds.louvain.stats($name, {relationshipWeightProperty: 'weight', concurrency: 1}) YIELD communityCount, modularity RETURN communityCount AS c, modularity AS q", name=name)
    return {
        "nodes": nodes,
        "edges": edges,
        "avg_degree": round(2 * edges / nodes, 3) if nodes else 0,
        "density": round(2 * edges / (nodes * (nodes - 1)), 6) if nodes > 1 else 0,
        "components": wcc["c"],
        "largest_component": wcc["m"],
        "largest_component_share": round(wcc["m"] / nodes, 3) if nodes else 0,
        "louvain_communities": lv["c"],
        "modularity": round(lv["q"], 4),
    }


def _project_collab(session, name: str, include_show: bool = True, y0: int = 0, y1: int = 9999) -> tuple[int, int]:
    _drop(session, name)
    r = _one(session, PROJECT_COLLAB, name=name, include_show=include_show, y0=y0, y1=y1)
    return r["nodes"], r["edges"]


def overview(session) -> None:
    print("12.1 Thống kê toàn mạng")
    nodes = _df(session, "MATCH (n:Entity) RETURN [l IN labels(n) WHERE l <> 'Entity'][0] AS entity_type, count(*) AS n ORDER BY n DESC")
    _save(nodes, "nodes_by_type.csv")
    rels = _df(session, "MATCH (:Entity)-[r]->(:Entity) RETURN type(r) AS relation_type, sum(CASE WHEN r.is_derived THEN 0 ELSE 1 END) AS direct, sum(CASE WHEN r.is_derived THEN 1 ELSE 0 END) AS derived, count(*) AS total ORDER BY total DESC")
    _save(rels, "relations_by_type.csv")
    sources = _df(session, "MATCH (d:Document)<-[:FROM_DOCUMENT]-(:Evidence) RETURN d.platform AS platform, d.content_tag AS content_tag, substring(d.published_at, 0, 4) AS year, count(DISTINCT d) AS documents ORDER BY year, platform, content_tag")
    _save(sources, "documents_by_source_year.csv")

    _drop(session, "full")
    full = _one(session, PROJECT_FULL, name="full")
    wcc = _one(session, "CALL gds.wcc.stats('full') YIELD componentCount, componentDistribution RETURN componentCount AS c, componentDistribution.max AS m")
    _drop(session, "full")
    isolated = _one(session, "MATCH (n:Entity) WHERE NOT (n)--(:Entity) RETURN count(n) AS v")["v"]
    summary = pd.DataFrame(
        [
            ("Nút thực thể", full["nodes"]),
            ("Cạnh nghiệp vụ", int(rels.total.sum())),
            ("Cạnh trích trực tiếp", int(rels.direct.sum())),
            ("Cạnh suy ra (is_derived)", int(rels.derived.sum())),
            ("Loại quan hệ có dữ liệu", len(rels)),
            ("Nút cô lập", isolated),
            ("Thành phần liên thông yếu", wcc["c"]),
            ("Nút trong thành phần lớn nhất", wcc["m"]),
            ("Tài liệu làm bằng chứng", int(sources.documents.sum())),
        ],
        columns=["metric", "value"],
    )
    _save(summary, "overview.csv")


def collaboration(session) -> pd.DataFrame:
    print("12.2–12.3 Mạng hợp tác nghệ sĩ")
    rows = []
    for variant, include_show in [("có tiết mục chương trình", True), ("chỉ sản phẩm chính thức", False)]:
        name = f"{COLLAB}_{int(include_show)}"
        n, e = _project_collab(session, name, include_show)
        rows.append({"variant": variant, **_network_stats(session, name, n, e)})
        if not include_show:
            alt = _df(session, f"CALL gds.pageRank.stream('{name}', {{relationshipWeightProperty: 'weight'}}) YIELD nodeId, score RETURN gds.util.asNode(nodeId).entity_id AS entity_id, score ORDER BY score DESC LIMIT {TOP}")
            _drop(session, name)
    _save(pd.DataFrame(rows), "collab_summary.csv")

    name = f"{COLLAB}_1"
    session.run(f"MATCH (n:Entity) REMOVE {', '.join('n.' + p for p in METRIC_PROPS)}").consume()
    weight = "relationshipWeightProperty: 'weight'"
    for proc, prop, cfg in [
        ("louvain", "community", f"{weight}, concurrency: 1"),
        ("pageRank", "pagerank", weight),
        ("betweenness", "betweenness", ""),
        ("degree", "collab_degree", ""),
        ("degree", "collab_strength", weight),
        ("wcc", "component", ""),
    ]:
        session.run(f"CALL gds.{proc}.write('{name}', {{writeProperty: '{prop}'{', ' + cfg if cfg else ''}}})").consume()
    _drop(session, name)

    metrics = _df(
        session,
        """
        MATCH (a:Entity) WHERE a.community IS NOT NULL
        OPTIONAL MATCH (a)-[:COLLABORATED_WITH]-(b:Entity)
        WITH a, count(DISTINCT b.community) AS neighbor_communities
        RETURN a.entity_id AS entity_id, a.name AS name, [l IN labels(a) WHERE l <> 'Entity'][0] AS entity_type,
               a.is_seed AS is_seed, a.genre_group AS genre_group, a.community AS community, a.component AS component,
               toInteger(a.collab_degree) AS degree, toInteger(a.collab_strength) AS strength, a.pagerank AS pagerank,
               a.betweenness AS betweenness, neighbor_communities
        """,
    )
    for col in ["degree", "strength", "pagerank", "betweenness"]:
        metrics[f"rank_{col}"] = metrics[col].rank(ascending=False, method="min").astype(int)
    metrics["rank_pagerank_no_show"] = metrics.entity_id.map({k: i + 1 for i, k in enumerate(alt.entity_id)})
    _save(metrics.sort_values("pagerank", ascending=False), "artist_metrics.csv")

    tops = []
    for col, label in [("degree", "Nhiều cộng sự (Degree)"), ("strength", "Nhiều lượt hợp tác (tổng trọng số)"), ("pagerank", "PageRank"), ("betweenness", "Cầu nối (Betweenness)")]:
        t = metrics.nlargest(TOP, col)[["name", "entity_type", "genre_group", "community", col, "neighbor_communities"]].rename(columns={col: "value"})
        tops.append(t.assign(metric=label, rank=range(1, len(t) + 1)))
    _save(pd.concat(tops)[["metric", "rank", "name", "entity_type", "genre_group", "community", "value", "neighbor_communities"]], "top_artists.csv")
    _save(metrics.degree.value_counts().sort_index().rename_axis("degree").reset_index(name="n_artists"), "degree_distribution.csv")
    return metrics


def communities(session, metrics: pd.DataFrame) -> None:
    print("RQ1, RQ4, RQ5: hồ sơ cộng đồng")
    songs = _df(session, "MATCH (a:Entity)-[:PERFORMED|FEATURED_ON]->(s:Song) WHERE a.community IS NOT NULL RETURN DISTINCT a.community AS community, s.entity_id AS song")
    companies = _df(session, "MATCH (a:Entity)-[:PERFORMED|FEATURED_ON]->(s:Song)-[:RELEASED_BY]->(c:Company) WHERE a.community IS NOT NULL RETURN a.community AS community, c.name AS company, count(DISTINCT s) AS songs")
    creators = _df(
        session,
        "MATCH (a:Entity)-[:PERFORMED|FEATURED_ON]->(s:Song)<-[r:COMPOSED|PRODUCED]-(w:Person) WHERE a.community IS NOT NULL RETURN a.community AS community, w.name AS creator, type(r) AS role, count(DISTINCT s) AS songs",
    )
    own = _df(session, "MATCH (a:Entity)-[r:COMPOSED|PRODUCED]->(s:Song) WHERE a.community IS NOT NULL RETURN a.community AS community, type(r) AS role, count(DISTINCT s) AS songs")

    def top_names(df: pd.DataFrame, c, col: str, n: int = 5) -> str:
        sub = df[df.community == c].groupby(col).songs.sum().nlargest(n) if len(df) else pd.Series(dtype=int)
        return "; ".join(f"{k} ({v})" for k, v in sub.items())

    rows = []
    for c, members in metrics.groupby("community"):
        genres = members.genre_group.replace("", pd.NA).dropna()
        rows.append(
            {
                "community": c,
                "size": len(members),
                "seeds": int(members.is_seed.fillna(False).sum()),
                "top_members": "; ".join(members.nlargest(8, "pagerank").name),
                "main_genre": genres.value_counts().index[0] if len(genres) else "",
                "main_genre_share": round(genres.value_counts().iloc[0] / len(genres), 2) if len(genres) else None,
                "genres": "; ".join(f"{k} ({v})" for k, v in genres.value_counts().items()),
                "internal_edges": None,
                "songs_performed": int((songs.community == c).sum()) if len(songs) else 0,
                "songs_composed_by_members": int(own[(own.community == c) & (own.role == "COMPOSED")].songs.sum()) if len(own) else 0,
                "songs_produced_by_members": int(own[(own.community == c) & (own.role == "PRODUCED")].songs.sum()) if len(own) else 0,
                "top_companies": top_names(companies, c, "company"),
                "top_composers": top_names(creators[creators.role == "COMPOSED"] if len(creators) else creators, c, "creator"),
                "top_producers": top_names(creators[creators.role == "PRODUCED"] if len(creators) else creators, c, "creator"),
            }
        )
    internal = _df(session, "MATCH (a:Entity)-[r:COLLABORATED_WITH]-(b:Entity) WHERE a.community IS NOT NULL AND a.community = b.community AND a.entity_id < b.entity_id RETURN a.community AS community, count(r) AS n")
    prof = pd.DataFrame(rows)
    prof["internal_edges"] = prof.community.map(dict(zip(internal.community, internal.n)) if len(internal) else {}).fillna(0).astype(int)
    _save(prof.sort_values("size", ascending=False), "communities.csv")
    _save(metrics.sort_values(["community", "pagerank"], ascending=[True, False])[["community", "entity_id", "name", "entity_type", "genre_group", "pagerank", "degree"]], "community_members.csv")


def temporal(session) -> None:
    print("RQ3: thay đổi theo thời gian (năm đăng tài liệu bằng chứng sớm nhất)")
    rows = []
    for y0, y1 in PERIODS:
        name = f"{COLLAB}_{y0}"
        n, e = _project_collab(session, name, True, y0, y1)
        if n:
            rows.append({"period": f"{y0}–{y1}", **_network_stats(session, name, n, e)})
        _drop(session, name)
    _save(pd.DataFrame(rows), "collab_by_period.csv")
    yearly = _df(
        session,
        """
        MATCH (a:Entity)-[r]->(:Entity) WHERE r.first_year IS NOT NULL AND type(r) IN ['PERFORMED','FEATURED_ON','COMPOSED','PRODUCED','COLLABORATED_WITH','RELEASED_BY']
        RETURN r.first_year AS year, type(r) AS relation_type, count(r) AS new_relations, count(DISTINCT a) AS active_sources
        ORDER BY year, relation_type
        """,
    )
    _save(yearly, "relations_by_year.csv")


def companies_stats(session) -> None:
    print("Công ty phát hành (Song → Company)")
    df = _df(
        session,
        """
        MATCH (s:Song)-[:RELEASED_BY]->(c:Company)
        OPTIONAL MATCH (a:Entity)-[:PERFORMED|FEATURED_ON]->(s)
        RETURN c.entity_id AS entity_id, c.name AS company, count(DISTINCT s) AS songs, count(DISTINCT a) AS artists
        ORDER BY songs DESC
        """,
    )
    _save(df, "companies.csv")


def gephi(session) -> None:
    print("Xuất cho Gephi (Import Spreadsheet)")
    nodes = _df(session, "MATCH (a:Entity) WHERE a.community IS NOT NULL RETURN a.entity_id AS Id, a.name AS Label, [l IN labels(a) WHERE l <> 'Entity'][0] AS type, a.genre_group AS genre_group, a.community AS community, a.pagerank AS pagerank, a.betweenness AS betweenness, a.collab_degree AS degree")
    edges = _df(session, "MATCH (a:Entity)-[r:COLLABORATED_WITH]->(b:Entity) WHERE a.community IS NOT NULL AND b.community IS NOT NULL RETURN a.entity_id AS Source, b.entity_id AS Target, 'Undirected' AS Type, r.weight AS Weight, r.show_only AS show_only, r.first_year AS first_year")
    _save(nodes, "gephi_nodes.csv")
    _save(edges, "gephi_edges.csv")


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    driver = connect()
    with driver.session() as session:
        try:
            version = session.run("RETURN gds.version() AS v").single()["v"]
        except Exception:
            raise SystemExit("Database chưa cài plugin Graph Data Science (GDS). Trong Neo4j Desktop: chọn database → Plugins → Graph Data Science → Install, rồi Restart.")
        if not session.run("MATCH (n:Entity) RETURN count(n) > 0 AS ok").single()["ok"]:
            raise SystemExit("Neo4j chưa có dữ liệu; chạy `uv run python main.py neo4j load` trước.")
        print(f"Neo4j GDS {version}; kết quả ghi vào {OUT}")
        overview(session)
        metrics = collaboration(session)
        communities(session, metrics)
        temporal(session)
        companies_stats(session)
        gephi(session)
    driver.close()
