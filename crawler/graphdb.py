import os

import pandas as pd
from neo4j import GraphDatabase

from .common import read_seeds
from .config import INTERIM_DIR
from .graph import GRAPH_DIR, web_documents

BATCH = 2000
ENTITY_TYPES = {"Person", "Group", "Song", "Album", "Company", "Brand", "Show", "Event"}
ARTIST_ROLES = {"PERFORMED", "FEATURED_ON"}


def connect():
    uri = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    if not password:
        raise SystemExit("Thiếu NEO4J_PASSWORD trong .env (mật khẩu đặt khi tạo database trong Neo4j Desktop)")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
    except Exception as ex:
        raise SystemExit(f"Không kết nối được Neo4j tại {uri}: {ex}. Kiểm tra database đã Start trong Neo4j Desktop chưa.")
    return driver


def _csv(path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in ("", None) and not (isinstance(v, float) and pd.isna(v))}


def prepare() -> dict[str, pd.DataFrame]:
    entities = _csv(GRAPH_DIR / "entities.csv")
    relations = _csv(GRAPH_DIR / "relations.csv")
    evidence = _csv(GRAPH_DIR / "evidence.csv")
    documents = _csv(INTERIM_DIR / "documents.csv").drop(columns=["content"])
    documents = pd.concat([documents, pd.DataFrame(web_documents(), dtype=str)], ignore_index=True).fillna("")
    documents = documents[documents.document_id.isin(set(evidence.document_id))]

    genre = {s["seed_id"]: s.get("genre_group", "") for s in read_seeds()}
    entities["genre_group"] = entities.seed_id.map(genre).fillna("")

    ev = evidence.merge(documents[["document_id", "published_at", "content_tag"]], on="document_id", how="left")
    ev["year"] = pd.to_numeric(ev.published_at.str[:4], errors="coerce")
    per_rel = ev.groupby("relation_id").agg(
        first_year=("year", "min"),
        show_only=("content_tag", lambda s: bool(len(s)) and bool((s == "performance_show").all())),
    )
    relations = relations.merge(per_rel, left_on="relation_id", right_index=True, how="left")

    # Trọng số hợp tác = số bài khác nhau cả hai cùng trình bày (Bước 12.2), không phải số tài liệu nhắc đến.
    songs = relations[relations.relation_type.isin(ARTIST_ROLES)].groupby("source_entity_id").target_entity_id.agg(set).to_dict()
    collab = relations.relation_type == "COLLABORATED_WITH"
    relations["weight"] = None
    relations.loc[collab, "weight"] = [
        max(1, len(songs.get(a, set()) & songs.get(b, set())))
        for a, b in zip(relations.loc[collab, "source_entity_id"], relations.loc[collab, "target_entity_id"])
    ]
    return {"entities": entities, "relations": relations, "evidence": evidence, "documents": documents}


def _entity_props(e: dict) -> dict:
    return _clean(
        {
            "entity_id": e["entity_id"],
            "name": e["canonical_name"],
            "aliases": [a.strip() for a in e["aliases"].split("|") if a.strip()],
            "verification_status": e["verification_status"],
            "created_at": e["created_at"],
            "notes": e["notes"],
            "release_year": _int(e["release_year"]),
            "season_or_year": e["season_or_year"],
            "official_url": e["official_url"],
            "seed_id": e["seed_id"],
            "is_seed": bool(e["seed_id"]),
            "genre_group": e["genre_group"],
            "n_documents": _int(e["n_documents"]),
        }
    )


def _relation_props(r: dict) -> dict:
    return _clean(
        {
            "relation_id": r["relation_id"],
            "verification_status": r["verification_status"],
            "is_derived": r["is_derived"] == "có",
            "valid_from": r["valid_from"],
            "valid_to": r["valid_to"],
            "role_detail": r["role_detail"],
            "notes": r["notes"],
            "n_documents": _int(r["n_documents"]),
            "first_year": _int(r["first_year"]),
            "show_only": bool(r["show_only"]) if r["show_only"] is not None and not pd.isna(r["show_only"]) else None,
            "weight": _int(r["weight"]),
        }
    )


def _run_batches(session, query: str, rows: list[dict]) -> int:
    created = 0
    for i in range(0, len(rows), BATCH):
        counters = session.run(query, rows=rows[i : i + BATCH]).consume().counters
        created += counters.nodes_created + counters.relationships_created
    return created


def load() -> None:
    data = prepare()
    check_tables(data)
    entities, relations, evidence, documents = data["entities"], data["relations"], data["evidence"], data["documents"]
    bad_types = set(entities.entity_type) - ENTITY_TYPES
    if bad_types:
        raise SystemExit(f"Loại thực thể lạ trong entities.csv: {bad_types}")
    rel_types = sorted(set(relations.relation_type))
    if any(not t.replace("_", "").isalpha() or not t.isupper() for t in rel_types):
        raise SystemExit(f"Tên quan hệ không hợp lệ: {rel_types}")

    driver = connect()
    with driver.session() as session:
        print("Xóa dữ liệu cũ trong database…")
        session.run("MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS").consume()
        for q in [
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.document_id IS UNIQUE",
            "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.evidence_id IS UNIQUE",
            "CREATE INDEX evidence_relation IF NOT EXISTS FOR (n:Evidence) ON (n.relation_id)",
            "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
        ]:
            session.run(q).consume()

        n_nodes = 0
        for etype, group in entities.groupby("entity_type"):
            rows = [_entity_props(e) for e in group.to_dict("records")]
            n_nodes += _run_batches(session, f"UNWIND $rows AS row CREATE (n:Entity:{etype}) SET n = row", rows)
        print(f"  Nút thực thể: {n_nodes}/{len(entities)}")

        n_rels = 0
        for rtype, group in relations.groupby("relation_type"):
            rows = [{"s": r["source_entity_id"], "t": r["target_entity_id"], "props": _relation_props(r)} for r in group.to_dict("records")]
            q = f"UNWIND $rows AS row MATCH (a:Entity {{entity_id: row.s}}) MATCH (b:Entity {{entity_id: row.t}}) CREATE (a)-[r:{rtype}]->(b) SET r = row.props"
            made = _run_batches(session, q, rows)
            n_rels += made
            if made != len(rows):
                print(f"  ⚠ {rtype}: {len(rows) - made} cạnh thiếu nút đầu/cuối")
        print(f"  Cạnh nghiệp vụ: {n_rels}/{len(relations)} ({len(rel_types)} loại)")

        doc_cols = ["document_id", "url", "source_name", "source_type", "title", "published_at", "collected_at", "collection_method", "document_status", "account_verified", "platform", "content_tag", "seed_ids"]
        rows = [_clean(d) for d in documents[doc_cols].to_dict("records")]
        print(f"  Nút Document: {_run_batches(session, 'UNWIND $rows AS row CREATE (d:Document) SET d = row', rows)}")

        ev_cols = ["evidence_id", "relation_id", "quote", "sentence_location", "extraction_method", "review_status", "review_note", "confidence_score"]
        rows = [{"doc": e["document_id"], "props": _clean({**{c: e[c] for c in ev_cols}, "confidence_score": float(e["confidence_score"]) if e["confidence_score"] else None})} for e in evidence.to_dict("records")]
        q = "UNWIND $rows AS row MATCH (d:Document {document_id: row.doc}) CREATE (e:Evidence)-[:FROM_DOCUMENT]->(d) SET e = row.props"
        print(f"  Nút Evidence + cạnh FROM_DOCUMENT: {_run_batches(session, q, rows)} (cần {2 * len(evidence)})")

        check(session)
    driver.close()


def check_tables(data: dict[str, pd.DataFrame]) -> None:
    ents, rels, ev, docs = data["entities"], data["relations"], data["evidence"], data["documents"]
    ids = set(ents.entity_id)
    pairs = rels[rels.relation_type == "COLLABORATED_WITH"].apply(lambda r: frozenset((r.source_entity_id, r.target_entity_id)), axis=1)
    print("Kiểm tra bảng trước khi nạp:")
    for label, v in {
        "Trùng entity_id": ents.entity_id.duplicated().sum(),
        "Trùng relation_id": rels.relation_id.duplicated().sum(),
        "Trùng (nguồn, loại, đích)": rels.duplicated(["source_entity_id", "relation_type", "target_entity_id"]).sum(),
        "Cặp COLLABORATED_WITH bị lặp hai chiều": pairs.duplicated().sum(),
        "Cạnh thiếu nút đầu/cuối": (~rels.source_entity_id.isin(ids) | ~rels.target_entity_id.isin(ids)).sum(),
        "Bằng chứng trỏ tới cạnh không tồn tại": (~ev.relation_id.isin(set(rels.relation_id))).sum(),
        "Bằng chứng trỏ tới tài liệu không tồn tại": (~ev.document_id.isin(set(docs.document_id))).sum(),
        "Bằng chứng thiếu câu trích": (ev.quote.str.strip() == "").sum(),
    }.items():
        print(f"  {label}: {v}")


CHECKS = {
    "Cạnh nghiệp vụ không có bằng chứng": "MATCH (a:Entity)-[r]->(b:Entity) WHERE NOT EXISTS { MATCH (e:Evidence {relation_id: r.relation_id}) } RETURN count(r) AS v",
    "Cạnh Person/Group → Song sai loại nút": "MATCH (a)-[r:PERFORMED|COMPOSED|PRODUCED|FEATURED_ON]->(b) WHERE NOT (a:Person OR a:Group) OR NOT b:Song RETURN count(r) AS v",
    "RELEASED_BY không phải Song/Album → Company": "MATCH (a)-[r:RELEASED_BY]->(b) WHERE NOT (a:Song OR a:Album) OR NOT b:Company RETURN count(r) AS v",
    "Nút thực thể không có cạnh": "MATCH (n:Entity) WHERE NOT (n)--(:Entity) RETURN count(n) AS v",
}


def check(session) -> None:
    print("Kiểm tra graph (Bước 11):")
    for label, q in CHECKS.items():
        print(f"  {label}: {session.run(q).single()['v']}")
