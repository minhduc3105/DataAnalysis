import math
import hashlib
import json
import random
from collections import Counter

import networkx as nx
import numpy as np
import pandas as pd

from .config import INTERIM_DIR, VN_TZ
from .graphdb import connect

OUT = INTERIM_DIR / "analysis"
COLLAB = "collab"
PERIODS = [(2016, 2020), (2021, 2026)]
TOP = 30
METRIC_PROPS = ["community", "pagerank", "betweenness", "collab_degree", "collab_strength", "component", "eigenvector", "core", "leiden"]
RANDOM_GRAPHS = 20
RANDOM_SOURCES = 300
FULL_SOURCES = 500
LEIDEN_RUNS = 10
SEED = 42
RUN_METADATA: dict = {}
RUN_DIR = None
ROLE_LABEL = {"PERFORMED": "Ca sĩ/rapper", "COMPOSED": "Nhạc sĩ", "PRODUCED": "Producer"}

COLLAB_EDGES = """
MATCH (a:Entity)-[r:COLLABORATED_WITH]->(b:Entity)
WHERE (a:Person OR a:Group) AND (b:Person OR b:Group)
RETURN a.entity_id AS a, b.entity_id AS b, r.weight AS w
"""
FULL_EDGES = "MATCH (a:Entity)-[r]->(b:Entity) RETURN a.entity_id AS a, b.entity_id AS b"

# Mạng hợp tác (Bước 12.2): nút nghệ sĩ/nhóm, cạnh COLLABORATED_WITH vô hướng, trọng số = số bài chung.
PROJECT_COLLAB = """
MATCH (a:Entity)-[r:COLLABORATED_WITH]->(b:Entity)
WHERE (a:Person OR a:Group) AND (b:Person OR b:Group)
  AND ($include_show OR NOT coalesce(r.show_only, false))
  AND r.first_year >= $y0 AND r.first_year <= $y1
WITH gds.graph.project($name, a, b, {relationshipProperties: r {.weight}}, {undirectedRelationshipTypes: ['*']}) AS g
RETURN g.nodeCount AS nodes, g.relationshipCount / 2 AS edges
"""

PROJECT_PERIOD_COLLAB = """
MATCH (a:Entity)-[r:COLLABORATED_WITH]-(b:Entity)
WHERE (a:Person OR a:Group) AND (b:Person OR b:Group) AND a.entity_id < b.entity_id
  AND ($include_show OR NOT coalesce(r.show_only, false))
MATCH (e:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
WHERE toInteger(substring(d.published_at, 0, 4)) >= $y0 AND toInteger(substring(d.published_at, 0, 4)) <= $y1
WITH a, b, count(DISTINCT d.document_id) AS weight
WITH gds.graph.project($name, a, b, {relationshipProperties: {weight: weight}}, {undirectedRelationshipTypes: ['*']}) AS g
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
    if RUN_METADATA:
        df = df.copy()
        df["analysis_run_id"] = RUN_METADATA["analysis_run_id"]
        df["graph_version"] = RUN_METADATA["graph_version"]
    df.to_csv(OUT / name, index=False, encoding="utf-8-sig")
    if RUN_DIR is not None:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(RUN_DIR / name, index=False, encoding="utf-8-sig")
    print(f"  → {name} ({len(df)} dòng)")


def _graph_version(session) -> tuple[str, int, int]:
    def ordered(value) -> list:
        if isinstance(value, list):
            return sorted(value)
        return [value] if value else []

    entities = []
    for row in session.run("MATCH (n:Entity) RETURN [n.entity_id,labels(n),n.name,coalesce(n.aliases,[])] AS key ORDER BY key[0]"):
        key = row["key"]
        key[1] = ordered(key[1])
        key[3] = ordered(key[3])
        entities.append(key)
    relations = []
    for row in session.run("MATCH (a:Entity)-[r]->(b:Entity) RETURN [r.relation_id,type(r),a.entity_id,b.entity_id,r.first_year,r.weight,r.verification_status,r.confidence,coalesce(r.model_versions,[])] AS key ORDER BY key[0]"):
        key = row["key"]
        key[8] = ordered(key[8])
        relations.append(key)
    evidence = []
    for row in session.run("MATCH (e:Evidence)-[:FROM_DOCUMENT]->(d:Document) RETURN [e.evidence_id,e.relation_id,e.quote,d.document_id,d.published_at,d.url,d.source_name,e.review_status,coalesce(e.model_versions,[])] AS key ORDER BY key[0]"):
        key = row["key"]
        key[8] = ordered(key[8])
        evidence.append(key)
    payload = json.dumps([entities, relations, evidence], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    rel_count = session.run("MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS n").single()["n"]
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16], len(entities), rel_count


def _save_enrichment_comparison(metrics: pd.DataFrame, graph_version: str, nodes: int, relations: int) -> None:
    baseline_dir = OUT / "baseline"
    baseline_metrics = baseline_dir / "artist_metrics.csv"
    baseline_manifest = baseline_dir / "manifest.json"
    delta_rows = [{"metric": "Entity count", "baseline": None, "current": nodes, "change": None, "note": "Chạy lại analyze trước khi nhập model để ghi nhận baseline có phiên bản."},
                  {"metric": "Relation count", "baseline": None, "current": relations, "change": None, "note": "Baseline phân tích chưa được lưu."}]
    if baseline_manifest.exists() and baseline_metrics.exists():
        meta = json.loads(baseline_manifest.read_text(encoding="utf-8"))
        old_nodes, old_relations = meta.get("nodes", 0), meta.get("relations", 0)
        delta_rows = [
            {"metric": "Entity count", "baseline": old_nodes, "current": nodes, "change": nodes - old_nodes, "note": "Neo4j nodes :Entity"},
            {"metric": "Relation count", "baseline": old_relations, "current": relations, "change": relations - old_relations, "note": "Business relationships"},
        ]
        old = pd.read_csv(baseline_metrics, encoding="utf-8-sig")
        joined = metrics.merge(old[["entity_id", "pagerank", "community"]].rename(columns={"pagerank": "baseline_pagerank", "community": "baseline_community"}), on="entity_id", how="left")
        joined["pagerank_change"] = joined.pagerank - joined.baseline_pagerank
        joined["baseline_rank"] = joined.baseline_pagerank.rank(ascending=False, method="min")
        joined["current_rank"] = joined.pagerank.rank(ascending=False, method="min")
        joined["rank_change"] = joined.baseline_rank - joined.current_rank
        _save(joined.sort_values("pagerank_change", ascending=False)[["entity_id", "name", "baseline_pagerank", "pagerank", "pagerank_change", "baseline_rank", "current_rank", "rank_change", "baseline_community", "community"]], "pagerank_change_after_enrichment.csv")
        overlap = len(set(old.nlargest(20, "pagerank").entity_id) & set(metrics.nlargest(20, "pagerank").entity_id))
        paired = joined.dropna(subset=["baseline_community", "community"])
        nmi = _nmi(paired.baseline_community, paired.community) if len(paired) else None
        delta_rows.extend([
            {"metric": "Top 20 PageRank overlap", "baseline": 20, "current": overlap, "change": overlap - 20, "note": "Entity IDs xuất hiện ở cả hai danh sách"},
            {"metric": "New entities in current", "baseline": 0, "current": int((~metrics.entity_id.isin(set(old.entity_id))).sum()), "change": int((~metrics.entity_id.isin(set(old.entity_id))).sum()), "note": "Entity chưa có trong baseline"},
            {"metric": "NMI community", "baseline": "baseline vs current", "current": round(nmi, 4) if nmi is not None else None, "change": None, "note": "So sánh trên các entity ID chung"},
        ])
    else:
        _save(pd.DataFrame(columns=["entity_id", "name", "baseline_pagerank", "pagerank", "pagerank_change", "baseline_rank", "current_rank", "rank_change", "baseline_community", "community"]), "pagerank_change_after_enrichment.csv")
    _save(pd.DataFrame(delta_rows), "graph_enrichment_delta.csv")
    if not baseline_manifest.exists():
        baseline_dir.mkdir(parents=True, exist_ok=True)
        baseline_metrics.write_bytes((OUT / "artist_metrics.csv").read_bytes())
        baseline_manifest.write_text(json.dumps({"graph_version": graph_version, "nodes": nodes, "relations": relations, "created_at": RUN_METADATA.get("generated_at")}, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Đã lưu baseline phân tích hiện tại; lần chạy sau sẽ xuất so sánh làm giàu.")


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
    query = PROJECT_PERIOD_COLLAB if y0 >= 2016 else PROJECT_COLLAB
    if y0 >= 2016:
        matching = _one(session, """
            MATCH (a:Entity)-[r:COLLABORATED_WITH]-(b:Entity)
            WHERE (a:Person OR a:Group) AND (b:Person OR b:Group) AND a.entity_id < b.entity_id
              AND ($include_show OR NOT coalesce(r.show_only,false))
            MATCH (e:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
            WHERE toInteger(substring(d.published_at,0,4)) >= $y0 AND toInteger(substring(d.published_at,0,4)) <= $y1
            RETURN count(DISTINCT r.relation_id) AS edges
        """, include_show=include_show, y0=y0, y1=y1)["edges"]
        if not matching:
            return 0, 0
    r = _one(session, query, name=name, include_show=include_show, y0=y0, y1=y1)
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
        ("eigenvector", "eigenvector", weight),
        ("kcore", "core", ""),
        ("leiden", "leiden", f"{weight}, randomSeed: {SEED}, concurrency: 1"),
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
               a.betweenness AS betweenness, a.eigenvector AS eigenvector, toInteger(a.core) AS core, a.leiden AS leiden,
               neighbor_communities
        """,
    )
    roles = _df(
        session,
        """
        MATCH (a:Entity)-[r:PERFORMED|FEATURED_ON|COMPOSED|PRODUCED]->(:Song) WHERE a.community IS NOT NULL
        RETURN a.entity_id AS entity_id, CASE type(r) WHEN 'FEATURED_ON' THEN 'PERFORMED' ELSE type(r) END AS role, count(*) AS n
        """,
    )
    main_role = roles.sort_values("n", ascending=False).drop_duplicates("entity_id").set_index("entity_id").role.map(ROLE_LABEL)
    metrics["main_role"] = metrics.entity_id.map(main_role).fillna("Khác")
    for col in ["degree", "strength", "pagerank", "betweenness", "eigenvector"]:
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


def _lcc(g: nx.Graph) -> nx.Graph:
    if not g.number_of_nodes():
        return g.copy()
    return g.subgraph(max(nx.connected_components(g), key=len)).copy()


def _distances(g: nx.Graph, sources=None) -> Counter:
    counts: Counter = Counter()
    for s in sources if sources is not None else g.nodes:
        counts.update(d for d in nx.single_source_shortest_path_length(g, s).values() if d)
    return counts


def _avg(counts: Counter) -> float:
    return sum(d * c for d, c in counts.items()) / sum(counts.values()) if counts else 0.0


def _sample(g: nx.Graph, k: int, rng: random.Random) -> list:
    nodes = list(g.nodes)
    return nodes if len(nodes) <= k else rng.sample(nodes, k)


def _nmi(a: pd.Series, b: pd.Series) -> float:
    p = pd.crosstab(a, b).to_numpy() / len(a)
    pa, pb = p.sum(1), p.sum(0)
    nz = p > 0
    mi = (p[nz] * np.log(p[nz] / np.outer(pa, pb)[nz])).sum()
    h = lambda q: -(q[q > 0] * np.log(q[q > 0])).sum()
    return float(2 * mi / (h(pa) + h(pb)))


def small_world(session, metrics: pd.DataFrame) -> None:
    print("2.1 Thế giới nhỏ (thành phần liên thông lớn nhất của mạng hợp tác)")
    rng = random.Random(SEED)
    edge_rows = _df(session, COLLAB_EDGES)
    g = _lcc(nx.from_pandas_edgelist(edge_rows, "a", "b") if not edge_rows.empty else nx.Graph())
    n, m = g.number_of_nodes(), g.number_of_edges()
    if n < 2:
        _save(pd.DataFrame([{"metric": "status", "value": "không đủ nút có cạnh để tính", "note": "Cần ít nhất hai nút trong thành phần liên thông."}]), "small_world.csv")
        _save(pd.DataFrame(columns=["model", "run", "seed", "nodes_lcc", "edges_lcc", "average_path_length", "average_clustering", "path_source_count", "path_measure", "error"]), "small_world_reference_runs.csv")
        _save(pd.DataFrame(columns=["distance", "pairs", "share"]), "distance_distribution.csv")
        _save(pd.DataFrame(columns=["from", "from_genre", "to", "to_genre", "hops", "path"]), "small_world_paths.csv")
        return
    k = 2 * m / n
    dist = _distances(g)
    L, C = _avg(dist), nx.average_clustering(g)

    reference_runs = []

    def reference(model: str, make) -> tuple[float, float]:
        ls, cs = [], []
        for run in range(RANDOM_GRAPHS):
            seed = rng.randrange(1 << 30)
            try:
                r = _lcc(make(seed))
                sources = _sample(r, RANDOM_SOURCES, rng)
                length = _avg(_distances(r, sources))
                clustering = nx.average_clustering(r) if r.number_of_nodes() else 0.0
            except Exception as exc:
                reference_runs.append({"model": model, "run": run + 1, "seed": seed, "nodes_lcc": None, "edges_lcc": None, "average_path_length": None, "average_clustering": None, "path_source_count": 0, "path_measure": "unavailable", "error": str(exc)[:300]})
                continue
            ls.append(length)
            cs.append(clustering)
            reference_runs.append({"model": model, "run": run + 1, "seed": seed, "nodes_lcc": r.number_of_nodes(), "edges_lcc": r.number_of_edges(), "average_path_length": round(length, 5), "average_clustering": round(clustering, 6), "path_source_count": len(sources), "path_measure": "exact" if len(sources) == r.number_of_nodes() else "sampled_sources", "error": ""})
        return (float(np.mean(ls)), float(np.mean(cs))) if ls else (float("nan"), float("nan"))

    def rewired(seed: int) -> nx.Graph:
        r = g.copy()
        if m > 1 and r.number_of_nodes() > 3:
            nx.double_edge_swap(r, nswap=2 * m, max_tries=40 * m, seed=seed)
        return r

    l_er, c_er = reference("erdos_renyi_gnm", lambda s: nx.gnm_random_graph(n, m, seed=s))
    l_cf, c_cf = reference("degree_preserving_swap", rewired)
    lattice_degree = min(max(2, int(round(k / 2) * 2)), n - 1)
    if lattice_degree % 2 and lattice_degree > 2:
        lattice_degree -= 1
    lattice = nx.watts_strogatz_graph(n, lattice_degree, 0, seed=SEED) if n >= 3 and lattice_degree >= 2 and n > lattice_degree else nx.complete_graph(n)
    c_lattice = nx.average_clustering(lattice) if n > 2 else 0

    full_edges = _df(session, FULL_EDGES)
    full = _lcc(nx.from_pandas_edgelist(full_edges, "a", "b") if not full_edges.empty else nx.Graph())
    l_full = _avg(_distances(full, _sample(full, FULL_SOURCES, rng)))

    rows = [
        ("Số nút (thành phần lớn nhất)", n, ""),
        ("Số cạnh", m, ""),
        ("Bậc trung bình k", round(k, 3), ""),
        ("Khoảng cách ngắn nhất trung bình L", round(L, 3), "tính trên mọi cặp nút"),
        ("Đường kính", max(dist), ""),
        ("Hệ số gom cụm trung bình C", round(C, 4), ""),
        ("Transitivity", round(nx.transitivity(g), 4), ""),
        ("L ngẫu nhiên Erdős–Rényi", round(l_er, 3), f"trung bình {RANDOM_GRAPHS} đồ thị cùng n, m"),
        ("C ngẫu nhiên Erdős–Rényi", round(c_er, 4), ""),
        ("L lý thuyết ln n / ln k", round(math.log(n) / math.log(k), 3) if k > 1 else None, ""),
        ("L ngẫu nhiên giữ phân phối bậc", round(l_cf, 3), f"{RANDOM_GRAPHS} đồ thị hoán đổi cạnh"),
        ("C ngẫu nhiên giữ phân phối bậc", round(c_cf, 4), ""),
        ("σ so với Erdős–Rényi", round((C / c_er) / (L / l_er), 2) if all(math.isfinite(v) and v > 0 for v in (c_er, L, l_er)) else None, "> 1 là thế giới nhỏ"),
        ("σ so với đồ thị giữ bậc", round((C / c_cf) / (L / l_cf), 2) if all(math.isfinite(v) and v > 0 for v in (c_cf, L, l_cf)) else None, "> 1 là thế giới nhỏ"),
        ("Hệ số gom cụm lưới tham chiếu", round(c_lattice, 4), f"Watts–Strogatz vòng; n={n}, degree={lattice_degree}, m={lattice.number_of_edges()}"),
        ("ω", round(l_er / L - C / c_lattice, 3) if math.isfinite(l_er) and c_lattice and L else None, "Telesford 2011; dùng L trung bình Erdős–Rényi lấy mẫu và C của lưới Watts–Strogatz hữu hạn"),
        ("L đồ thị tri thức đầy đủ", round(l_full, 3), f"{full.number_of_nodes()} nút, ước lượng từ {FULL_SOURCES} nút nguồn"),
    ]
    _save(pd.DataFrame(rows, columns=["metric", "value", "note"]), "small_world.csv")
    _save(pd.DataFrame(reference_runs), "small_world_reference_runs.csv")
    total = sum(dist.values())
    _save(pd.DataFrame([(d, c, round(c / total, 4)) for d, c in sorted(dist.items())], columns=["distance", "pairs", "share"]), "distance_distribution.csv")
    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(sorted(dist), [dist[d] / total for d in sorted(dist)], color="#1d5fbf", width=0.78)
        ax.set(xlabel="Khoảng cách ngắn nhất (bước)", ylabel="Tỷ lệ cặp có thứ tự", title="Phân phối khoảng cách trên thành phần liên thông lớn nhất")
        ax.grid(axis="y", color="#e8ebef", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(OUT / "small_world_distance.png", dpi=180)
        if RUN_DIR is not None:
            fig.savefig(RUN_DIR / "small_world_distance.png", dpi=180)
        plt.close(fig)
    except ImportError:
        print("matplotlib chưa cài; bỏ qua ảnh small_world_distance.png")

    names = dict(zip(metrics.entity_id, metrics.name))
    in_g = metrics[metrics.entity_id.isin(g.nodes) & metrics.genre_group.fillna("").ne("")]
    tops = in_g.sort_values("pagerank", ascending=False).drop_duplicates("genre_group")
    pairs = [(a, b) for i, a in enumerate(tops.itertuples()) for b in list(tops.itertuples())[i + 1:]]
    paths = []
    for a, b in pairs:
        p = nx.shortest_path(g, a.entity_id, b.entity_id)
        paths.append({"from": a.name, "from_genre": a.genre_group, "to": b.name, "to_genre": b.genre_group, "hops": len(p) - 1, "path": " → ".join(names.get(x, x) for x in p)})
    _save(pd.DataFrame(paths), "small_world_paths.csv")


def centrality(metrics: pd.DataFrame) -> None:
    print("2.2 So sánh các thước đo xếp hạng")
    cols = ["degree", "strength", "pagerank", "betweenness", "eigenvector"]
    _save(metrics[cols].corr(method="spearman").round(3).rename_axis("measure").reset_index(), "centrality_correlation.csv")
    top = {c: set(metrics.nlargest(20, c).entity_id) for c in cols}
    _save(pd.DataFrame([{"measure": c, "top20_overlap_with_pagerank": len(top[c] & top["pagerank"])} for c in cols]), "top20_overlap.csv")
    by_role = metrics[metrics.main_role != "Khác"].sort_values("pagerank", ascending=False).groupby("main_role").head(15)
    _save(by_role[["main_role", "name", "genre_group", "pagerank", "degree", "betweenness", "community"]].assign(rank=by_role.groupby("main_role").cumcount() + 1), "top_by_role.csv")


def community_structure(session, metrics: pd.DataFrame) -> None:
    print("2.3 Cộng đồng (Louvain so với Leiden) và hạt nhân (k-core)")
    name = f"{COLLAB}_cd"
    _project_collab(session, name, True)
    weight = "relationshipWeightProperty: 'weight'"
    louvain = _one(session, f"CALL gds.louvain.stats('{name}', {{{weight}, concurrency: 1}}) YIELD communityCount, modularity RETURN communityCount AS c, modularity AS q")
    runs, base = [], None
    for i in range(LEIDEN_RUNS):
        st = _one(session, f"CALL gds.leiden.stats('{name}', {{{weight}, randomSeed: {i}, concurrency: 1}}) YIELD communityCount, modularity RETURN communityCount AS c, modularity AS q")
        part = _df(session, f"CALL gds.leiden.stream('{name}', {{{weight}, randomSeed: {i}, concurrency: 1}}) YIELD nodeId, communityId RETURN gds.util.asNode(nodeId).entity_id AS entity_id, communityId AS c").set_index("entity_id").c
        base = part if base is None else base
        runs.append({"seed": i, "communities": st["c"], "modularity": st["q"], "nmi_vs_seed0": _nmi(base, part.reindex(base.index))})
    _drop(session, name)
    runs = pd.DataFrame(runs)
    _save(runs, "leiden_runs.csv")
    _save(
        pd.DataFrame(
            [
                ("Louvain", louvain["c"], round(louvain["q"], 4), "", ""),
                ("Leiden", int(runs.communities.median()), round(runs.modularity.mean(), 4), round(runs.modularity.std(), 4), round(runs.nmi_vs_seed0.mean(), 3)),
                ("NMI Louvain–Leiden", "", "", "", round(_nmi(metrics.community, metrics.leiden), 3)),
            ],
            columns=["method", "communities", "modularity", "modularity_std", "nmi"],
        ),
        "community_methods.csv",
    )

    _save(metrics.core.value_counts().sort_index().rename_axis("k").reset_index(name="n_nodes"), "kcore_distribution.csv")
    kmax = metrics.core.max()
    _save(metrics[metrics.core == kmax].sort_values("pagerank", ascending=False)[["name", "entity_type", "genre_group", "community", "core", "degree", "pagerank"]], "max_core.csv")

    edges = _df(session, COLLAB_EDGES)
    comm = dict(zip(metrics.entity_id, metrics.community))
    same = edges[edges.a.map(comm) == edges.b.map(comm)]
    internal = pd.concat([same.a, same.b]).value_counts()
    metrics = metrics.assign(internal_degree=metrics.entity_id.map(internal).fillna(0).astype(int))
    rows = []
    for c, mem in metrics.groupby("community"):
        if len(mem) < 5:
            continue
        core_k = mem.core.max()
        nucleus = mem[mem.core == core_k].sort_values("pagerank", ascending=False)
        rows.append(
            {
                "community": c,
                "size": len(mem),
                "main_genre": mem.genre_group.replace("", pd.NA).dropna().mode().iat[0] if mem.genre_group.replace("", pd.NA).notna().any() else "",
                "max_core_in_community": int(core_k),
                "nucleus_size": len(nucleus),
                "nucleus": "; ".join(nucleus.name.head(10)),
                "hub_internal_degree": mem.nlargest(1, "internal_degree").name.iat[0],
                "hub_pagerank": mem.nlargest(1, "pagerank").name.iat[0],
            }
        )
    _save(pd.DataFrame(rows).sort_values("size", ascending=False), "community_cores.csv")

    bridge_rows = _df(session, """
        MATCH (a:Entity)-[r:COLLABORATED_WITH]-(b:Entity)
        WHERE a.entity_id < b.entity_id AND a.community IS NOT NULL AND b.community IS NOT NULL
        RETURN a.entity_id AS a,a.name AS a_name,a.community AS community_a,
               b.entity_id AS b,b.name AS b_name,b.community AS community_b,
               r.relation_id AS relation_id,r.weight AS weight,r.first_year AS first_year,r.n_documents AS n_documents
    """)
    if len(bridge_rows):
        g = nx.from_pandas_edgelist(bridge_rows, "a", "b", edge_attr=["weight"])
        for _a, _b, data in g.edges(data=True):
            data["distance"] = 1 / max(float(data.get("weight") or 1), 1)
        score = nx.edge_betweenness_centrality(g, weight="distance")
        by_pair = {frozenset((r.a, r.b)): r._asdict() for r in bridge_rows.itertuples(index=False)}
        bridges = []
        for (a, b), value in score.items():
            if comm.get(a) == comm.get(b):
                continue
            row = by_pair[frozenset((a, b))]
            bridges.append({**row, "edge_betweenness": value})
        _save(pd.DataFrame(bridges).sort_values("edge_betweenness", ascending=False).head(100), "community_bridges.csv")
    else:
        _save(pd.DataFrame(columns=["a", "a_name", "community_a", "b", "b_name", "community_b", "relation_id", "weight", "first_year", "n_documents", "edge_betweenness"]), "community_bridges.csv")


def temporal(session) -> None:
    print("RQ3: thay đổi theo thời gian (năm đăng tài liệu bằng chứng sớm nhất)")
    rows, ranks = [], []
    for y0, y1 in PERIODS:
        name = f"{COLLAB}_{y0}"
        n, e = _project_collab(session, name, True, y0, y1)
        if n:
            rows.append({"period": f"{y0}–{y1}", **_network_stats(session, name, n, e)})
            top = _df(session, f"CALL gds.pageRank.stream('{name}', {{relationshipWeightProperty: 'weight'}}) YIELD nodeId, score RETURN gds.util.asNode(nodeId).name AS name, score ORDER BY score DESC LIMIT 10")
            ranks.append(top.assign(period=f"{y0}–{y1}", rank=range(1, len(top) + 1)))
        _drop(session, name)
    _save(pd.DataFrame(rows), "collab_by_period.csv")
    rank_columns = ["period", "rank", "name", "score"]
    _save(pd.concat(ranks, ignore_index=True)[rank_columns] if ranks else pd.DataFrame(columns=rank_columns), "pagerank_by_period.csv")
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
    _drop(session, "full_rank")
    _one(session, PROJECT_FULL, name="full_rank")
    ranked = _df(session, "CALL gds.pageRank.stream('full_rank') YIELD nodeId,score WITH gds.util.asNode(nodeId) AS n,score RETURN n.entity_id AS entity_id,n.name AS name,[l IN labels(n) WHERE l<>'Entity'][0] AS entity_type,score AS pagerank ORDER BY pagerank DESC")
    _drop(session, "full_rank")
    _save(ranked[ranked.entity_type.isin(["Company", "Song"])].groupby("entity_type", group_keys=False).head(TOP), "pagerank_song_company.csv")


def gephi(session) -> None:
    print("Xuất cho Gephi (Import Spreadsheet)")
    nodes = _df(session, "MATCH (a:Entity) WHERE a.community IS NOT NULL RETURN a.entity_id AS Id, a.name AS Label, [l IN labels(a) WHERE l <> 'Entity'][0] AS type, a.genre_group AS genre_group, a.community AS community, a.leiden AS leiden, a.core AS core, a.pagerank AS pagerank, a.betweenness AS betweenness, a.collab_degree AS degree")
    edges = _df(session, "MATCH (a:Entity)-[r:COLLABORATED_WITH]->(b:Entity) WHERE a.community IS NOT NULL AND b.community IS NOT NULL RETURN a.entity_id AS Source, b.entity_id AS Target, 'Undirected' AS Type, r.weight AS Weight, r.show_only AS show_only, r.first_year AS first_year")
    _save(nodes, "gephi_nodes.csv")
    _save(edges, "gephi_edges.csv")


def run() -> None:
    global RUN_METADATA, RUN_DIR
    OUT.mkdir(parents=True, exist_ok=True)
    driver = connect()
    with driver.session() as session:
        try:
            version = session.run("RETURN gds.version() AS v").single()["v"]
        except Exception:
            raise SystemExit("Database chưa cài plugin Graph Data Science (GDS). Trong Neo4j Desktop: chọn database → Plugins → Graph Data Science → Install, rồi Restart.")
        if not session.run("MATCH (n:Entity) RETURN count(n) > 0 AS ok").single()["ok"]:
            raise SystemExit("Neo4j chưa có dữ liệu; chạy `uv run python main.py neo4j load` trước.")
        graph_version, nodes, relations = _graph_version(session)
        generated_at = pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").isoformat()
        RUN_METADATA = {"analysis_run_id": f"analysis-{graph_version}-{pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').strftime('%Y%m%d%H%M%S')}", "graph_version": graph_version, "generated_at": generated_at, "gds_version": version}
        RUN_DIR = OUT / "snapshots" / f"graph-{graph_version}"
        print(f"Neo4j GDS {version}; graph={graph_version} ({nodes} nút, {relations} cạnh); kết quả ghi vào {OUT} và {RUN_DIR}")
        overview(session)
        metrics = collaboration(session)
        communities(session, metrics)
        community_structure(session, metrics)
        centrality(metrics)
        small_world(session, metrics)
        temporal(session)
        companies_stats(session)
        gephi(session)
        _save_enrichment_comparison(metrics, graph_version, nodes, relations)
        manifest = {**RUN_METADATA, "periods": [list(p) for p in PERIODS], "seed": SEED, "random_graphs": RANDOM_GRAPHS, "random_path_sources": RANDOM_SOURCES, "full_graph_path_sources": FULL_SOURCES, "leiden_runs": LEIDEN_RUNS, "small_world_main_lcc_path_measure": "exact", "graph_nodes": nodes, "graph_relations": relations}
        (OUT / "analysis_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        (RUN_DIR / "analysis_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    driver.close()
