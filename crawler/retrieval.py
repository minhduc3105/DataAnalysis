"""Neo4j graph/vector retrieval and evidence-grounded answer handoff."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any

import pandas as pd
from fastapi import HTTPException
from neo4j.exceptions import ClientError

from .common import now_iso
from .config import INTERIM_DIR, ROOT
from .graphdb import connect
from .model_contract import ModelClient, RELATION_SIGNATURES, SCHEMA_VERSION

RELATION_TYPES = sorted(RELATION_SIGNATURES)
INDEX_CONFIG = ROOT / "data/interim/analysis/index_manifest.json"


def ensure_indexes(dimensions: int | None = None) -> dict[str, Any]:
    client = ModelClient(timeout=float(os.getenv("MODEL_API_TIMEOUT", "120")))
    model, inferred, _ = client.embed(["VN Music Radar index dimension probe"])
    dimensions = dimensions or inferred
    if dimensions != inferred:
        raise ValueError(f"--dimensions={dimensions} nhưng /embed báo {inferred}")
    driver = connect()
    try:
        with driver.session() as session:
            session.run("CREATE FULLTEXT INDEX entity_name_alias IF NOT EXISTS FOR (n:Entity) ON EACH [n.name, n.aliases]").consume()
            session.run("CREATE FULLTEXT INDEX evidence_text IF NOT EXISTS FOR (e:Evidence) ON EACH [e.quote]").consume()
            old_meta = session.run("MATCH (m:Stage2Metadata {key:'embedding_index'}) RETURN m.model_version AS model,m.dimensions AS dimensions").single()
            model_changed = bool(old_meta and (old_meta["model"] != model or int(old_meta["dimensions"]) != dimensions))
            index_names = ("evidence_embedding", "entity_embedding")
            rows = {r["name"]: r.data() for r in session.run("SHOW INDEXES YIELD name, type, options WHERE name IN $names RETURN name, type, options", names=list(index_names))}
            recreate = set()
            for index_name in index_names:
                row = rows.get(index_name)
                config = row["options"].get("indexConfig", {}) if row else {}
                index_dimensions = config.get("vector.dimensions") or config.get("`vector.dimensions`")
                if model_changed or (row and int(index_dimensions or 0) != dimensions):
                    session.run(f"DROP INDEX {index_name} IF EXISTS").consume()
                    recreate.add(index_name)
            if model_changed:
                session.run("MATCH (e:Evidence) REMOVE e.embedding, e.embedding_model").consume()
                session.run("MATCH (n:Entity) REMOVE n.embedding, n.embedding_model").consume()
            else:
                if "evidence_embedding" in recreate:
                    session.run("MATCH (e:Evidence) REMOVE e.embedding, e.embedding_model").consume()
                if "entity_embedding" in recreate:
                    session.run("MATCH (n:Entity) REMOVE n.embedding, n.embedding_model").consume()
            for index_name in index_names:
                if not rows.get(index_name) or index_name in recreate:
                    label = "Evidence" if index_name == "evidence_embedding" else "Entity"
                    session.run(f"CREATE VECTOR INDEX {index_name} IF NOT EXISTS FOR (n:{label}) ON (n.embedding) OPTIONS {{indexConfig: {{`vector.dimensions`: {int(dimensions)}, `vector.similarity_function`: 'cosine'}}}}").consume()
            session.run("MERGE (m:Stage2Metadata {key:'embedding_index'}) SET m.model_version=$model, m.dimensions=$dimensions, m.updated_at=$at", model=model, dimensions=dimensions, at=now_iso()).consume()
    finally:
        driver.close()
    manifest = {"model_version": model, "dimensions": dimensions, "schema_version": SCHEMA_VERSION, "updated_at": now_iso()}
    INDEX_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    INDEX_CONFIG.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã tạo full-text/vector index: {manifest}")
    return manifest


def embed_evidence(batch_size: int = 48) -> dict[str, int]:
    client = ModelClient(timeout=float(os.getenv("MODEL_API_TIMEOUT", "120")))
    driver = connect()
    done = 0
    try:
        with driver.session() as session:
            while True:
                rows = [r.data() for r in session.run("MATCH (e:Evidence) WHERE e.quote IS NOT NULL AND e.embedding IS NULL RETURN e.evidence_id AS id, e.quote AS quote ORDER BY e.evidence_id LIMIT $n", n=batch_size)]
                if not rows:
                    break
                model, dimensions, vectors = client.embed([r["quote"] for r in rows])
                meta = session.run("MATCH (m:Stage2Metadata {key:'embedding_index'}) RETURN m.model_version AS model, m.dimensions AS dimensions").single()
                if meta and (meta["model"] != model or int(meta["dimensions"]) != dimensions):
                    raise RuntimeError("Mô hình/chiều embedding khác index; chạy `neo4j indexes` để dựng lại index trước khi tiếp tục")
                session.run("UNWIND $rows AS row MATCH (e:Evidence {evidence_id:row.id}) SET e.embedding=row.vector, e.embedding_model=$model", rows=[{"id": r["id"], "vector": v} for r, v in zip(rows, vectors)], model=model).consume()
                done += len(rows)
    finally:
        driver.close()
    print(f"Embedding bằng chứng mới: {done}")
    return {"embedded": done, "errors": 0}


def embed_entities(batch_size: int = 48) -> dict[str, int]:
    client = ModelClient(timeout=float(os.getenv("MODEL_API_TIMEOUT", "120")))
    driver = connect()
    done = 0
    try:
        with driver.session() as session:
            while True:
                rows = [r.data() for r in session.run("MATCH (n:Entity) WHERE n.name IS NOT NULL AND n.embedding IS NULL RETURN n.entity_id AS id,n.name AS name,coalesce(n.aliases,[]) AS aliases ORDER BY n.entity_id LIMIT $n", n=batch_size)]
                if not rows:
                    break
                texts = []
                for row in rows:
                    aliases = row["aliases"] if isinstance(row["aliases"], list) else ([row["aliases"]] if row["aliases"] else [])
                    texts.append("; ".join(dict.fromkeys([str(row["name"]), *(str(alias) for alias in aliases if str(alias).strip())])))
                model, dimensions, vectors = client.embed(texts)
                meta = session.run("MATCH (m:Stage2Metadata {key:'embedding_index'}) RETURN m.model_version AS model,m.dimensions AS dimensions").single()
                if not meta:
                    raise RuntimeError("Chưa có index; chạy `uv run python main.py neo4j indexes` trước")
                if meta["model"] != model or int(meta["dimensions"]) != dimensions:
                    raise RuntimeError("Mô hình/chiều embedding khác index; chạy `neo4j indexes` để dựng lại index trước khi tiếp tục")
                session.run("UNWIND $rows AS row MATCH (n:Entity {entity_id:row.id}) SET n.embedding=row.vector,n.embedding_model=$model", rows=[{"id": row["id"], "vector": vector} for row, vector in zip(rows, vectors)], model=model).consume()
                done += len(rows)
    finally:
        driver.close()
    print(f"Embedding thực thể mới: {done}")
    return {"embedded": done, "errors": 0}


def _entity_hits(session, question: str, limit: int = 8) -> list[dict[str, Any]]:
    exact = [r.data() for r in session.run("""
        MATCH (n:Entity)
        WHERE toLower(n.name) CONTAINS toLower($q) OR any(a IN coalesce(n.aliases,[]) WHERE toLower(a) CONTAINS toLower($q))
        RETURN n.entity_id AS id, n.name AS name, n.pagerank AS pagerank
        ORDER BY (toLower(n.name)=toLower($q)) DESC, coalesce(n.pagerank,0) DESC LIMIT $limit
    """, q=question, limit=limit)]
    if exact:
        return exact
    tokens = sorted({t.strip(".,!?()“”\"'^") for t in question.split() if len(t.strip(".,!?()“”\"'^") ) >= 4}, key=len, reverse=True)[:6]
    hits = {}
    for token in tokens:
        try:
            candidates = list(session.run("CALL db.index.fulltext.queryNodes('entity_name_alias',$q) YIELD node,score RETURN node.entity_id AS id,node.name AS name,node.pagerank AS pagerank ORDER BY score DESC,coalesce(node.pagerank,0) DESC LIMIT $limit", q=token, limit=limit))
        except ClientError:
            candidates = list(session.run("MATCH (n:Entity) WHERE toLower(n.name) CONTAINS toLower($q) OR any(a IN coalesce(n.aliases,[]) WHERE toLower(a) CONTAINS toLower($q)) RETURN n.entity_id AS id,n.name AS name,n.pagerank AS pagerank ORDER BY coalesce(n.pagerank,0) DESC LIMIT $limit", q=token, limit=limit))
        for r in candidates:
            row = r.data()
            hits[row["id"]] = row
    return sorted(hits.values(), key=lambda r: r.get("pagerank") or 0, reverse=True)[:limit]


def retrieve_graph(session, question: str, max_hops: int = 3, relation_types: list[str] | None = None, date_from: str | None = None, date_to: str | None = None, limit: int = 30) -> dict[str, Any]:
    max_hops = max(1, min(int(max_hops), 3))
    relation_types = relation_types or RELATION_TYPES
    if any(r not in RELATION_SIGNATURES for r in relation_types):
        raise HTTPException(400, "relation_types có giá trị không hợp lệ")
    seeds = _entity_hits(session, question)
    if not seeds:
        return {"method": "graph", "status": "no_entity_match", "seeds": [], "items": []}
    params = {"ids": [r["id"] for r in seeds], "types": relation_types, "date_from": date_from, "date_to": date_to, "limit": max(100, min(limit * 8, 240))}
    path_types = "|".join(sorted(relation_types))
    rows = [r.data() for r in session.run(f"""
        MATCH (a:Entity) WHERE a.entity_id IN $ids
        MATCH p=(a)-[:{path_types}*1..{max_hops}]-(b:Entity)
        WHERE all(r IN relationships(p) WHERE type(r) IN $types AND EXISTS {{
            MATCH (ev:Evidence {{relation_id:r.relation_id}})-[:FROM_DOCUMENT]->(d:Document)
            WHERE ($date_from IS NULL OR d.published_at >= $date_from) AND ($date_to IS NULL OR d.published_at <= $date_to)
        }})
        RETURN [n IN nodes(p) | {{id:n.entity_id,name:n.name,type:labels(n)[1],pagerank:n.pagerank}}] AS nodes,
               [r IN relationships(p) | {{relation:type(r),relation_id:r.relation_id,source:startNode(r).entity_id,target:endNode(r).entity_id,first_year:r.first_year,weight:r.weight}}] AS edges
        ORDER BY length(p) LIMIT $limit
    """, **params)]
    best: dict[tuple[str, ...], dict] = {}
    for row in rows:
        ids = tuple(n["id"] for n in row["nodes"])
        canonical = min(ids, tuple(reversed(ids)))
        if canonical in best:
            continue
        rel_ids = [e["relation_id"] for e in row["edges"] if e.get("relation_id")]
        evidence = []
        if rel_ids:
            evidence = [r.data() for r in session.run("""
                UNWIND $ids AS rid
                MATCH (e:Evidence {relation_id:rid})-[:FROM_DOCUMENT]->(d:Document)
                WHERE ($date_from IS NULL OR d.published_at >= $date_from) AND ($date_to IS NULL OR d.published_at <= $date_to)
                RETURN rid AS relation_id,e.evidence_id AS evidence_id,e.quote AS quote,d.title AS title,d.url AS url,d.source_name AS source,d.published_at AS published_at
                ORDER BY d.published_at DESC
            """, ids=rel_ids, date_from=date_from, date_to=date_to)]
        by_rel: dict[str, list[dict]] = defaultdict(list)
        for ev in evidence:
            by_rel[ev["relation_id"]].append(ev)
        for edge in row["edges"]:
            edge["evidence"] = by_rel.get(edge["relation_id"], [])[:3]
        row["hop_count"] = len(row["edges"])
        row["pagerank_sum"] = sum(float(n.get("pagerank") or 0) for n in row["nodes"])
        row["last_evidence_at"] = max((ev.get("published_at") or "" for ev in evidence), default="")
        row["has_evidence"] = all(bool(edge["evidence"]) for edge in row["edges"])
        if row["has_evidence"]:
            best[canonical] = row
    items = sorted(best.values(), key=lambda r: (-r["hop_count"], r["pagerank_sum"], r["last_evidence_at"]), reverse=True)[:limit]
    return {"method": "graph", "status": "ok" if items else "no_supported_path", "seeds": seeds, "items": items}


def retrieve_vector(session, question: str, limit: int = 40, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
    client = ModelClient(timeout=float(os.getenv("MODEL_API_TIMEOUT", "120")))
    model, dimensions, vectors = client.embed([question])
    meta = session.run("MATCH (m:Stage2Metadata {key:'embedding_index'}) RETURN m.model_version AS model,m.dimensions AS dimensions").single()
    if not meta:
        raise HTTPException(503, "Chưa tạo index embedding; chạy `uv run python main.py neo4j indexes`")
    if meta["model"] != model or int(meta["dimensions"]) != dimensions:
        raise HTTPException(503, "Embedding model/chiều đã đổi; chạy lại `neo4j indexes` và `retrieval embed`")
    candidate_limit = min(max(limit * 8, 120), 500)
    rows = [r.data() for r in session.run("""
        CALL db.index.vector.queryNodes('evidence_embedding',$candidate_limit,$embedding) YIELD node,score
        MATCH (node)-[:FROM_DOCUMENT]->(d:Document)
        WHERE ($date_from IS NULL OR d.published_at >= $date_from) AND ($date_to IS NULL OR d.published_at <= $date_to)
        RETURN node.evidence_id AS evidence_id,node.relation_id AS relation_id,node.quote AS quote,d.title AS title,d.url AS url,d.source_name AS source,d.published_at AS published_at,score
        ORDER BY score DESC LIMIT $limit
    """, candidate_limit=candidate_limit, limit=limit, embedding=vectors[0], date_from=date_from, date_to=date_to)]
    return {"method": "vector", "status": "ok" if rows else "no_evidence", "model_version": model, "items": rows}


def answer(question: str, retrieval: dict[str, Any], method: str) -> dict[str, Any]:
    items = retrieval.get("items", [])
    if not items or retrieval.get("status") not in {"ok"}:
        return {"status": retrieval.get("status", "no_evidence"), "answer": "Chưa tìm thấy đủ bằng chứng để trả lời câu hỏi.", "source_ids": [], "retrieval": retrieval}
    context = []
    for i, item in enumerate(items):
        if method == "graph":
            names = {node.get("id"): node.get("name", node.get("id", "")) for node in item.get("nodes", [])}
            graph_path = [{"relation": edge.get("relation"), "source": edge.get("source"), "source_name": names.get(edge.get("source")), "target": edge.get("target"), "target_name": names.get(edge.get("target"))} for edge in item.get("edges", [])]
            for edge in item.get("edges", []):
                for ev in edge.get("evidence", []):
                    context.append({"source_id": ev.get("evidence_id") or ev.get("relation_id"), "text": ev.get("quote", ""), "url": ev.get("url", ""), "title": ev.get("title", ""), "graph_path": graph_path, "path_rank": {"hops": item.get("hop_count"), "pagerank_sum": item.get("pagerank_sum"), "last_evidence_at": item.get("last_evidence_at")}})
        else:
            context.append({"source_id": item.get("evidence_id", f"vector-{i}"), "text": item.get("quote", ""), "url": item.get("url", ""), "title": item.get("title", "")})
    deduped = {}
    for citation in context:
        if citation["source_id"] and citation["text"]:
            deduped.setdefault(citation["source_id"], citation)
    context = list(deduped.values())
    if not context:
        return {"status": "no_evidence", "answer": "Chưa có câu bằng chứng để trả lời.", "source_ids": [], "retrieval": retrieval}
    payload = {"schema_version": SCHEMA_VERSION, "question": question, "context": context[:40]}
    result = ModelClient(timeout=float(os.getenv("MODEL_API_TIMEOUT", "120"))).post("answer", payload)
    if result.get("schema_version") != SCHEMA_VERSION or not str(result.get("model_version", "")).strip():
        return {"status": "model_contract_error", "answer": "Dịch vụ trả lời thiếu schema_version hoặc model_version theo hợp đồng v1.", "source_ids": [], "retrieval": retrieval}
    allowed = {c["source_id"] for c in payload["context"]}
    returned_ids = result.get("source_ids", [])
    if not isinstance(returned_ids, list):
        returned_ids = []
    source_ids = list(dict.fromkeys(str(s) for s in returned_ids if str(s) in allowed))
    if not source_ids:
        return {"status": "invalid_citations", "answer": "Dịch vụ trả lời không trỏ tới nguồn trong ngữ cảnh; chưa hiển thị câu trả lời.", "source_ids": [], "retrieval": retrieval}
    answer_text = str(result.get("answer", "")).strip()
    if not answer_text:
        return {"status": "empty_answer", "answer": "Dịch vụ trả lời chưa trả nội dung; chưa hiển thị kết luận.", "source_ids": [], "retrieval": retrieval}
    return {"status": "ok", "answer": answer_text, "source_ids": source_ids, "sources": [c for c in payload["context"] if c["source_id"] in source_ids], "retrieval": retrieval, "model_version": result.get("model_version", "")}


def export_communities() -> Path:
    from . import analysis

    path = INTERIM_DIR / "analysis" / "communities.csv"
    if not path.exists():
        raise FileNotFoundError("Chưa có kết quả cộng đồng; chạy `uv run python main.py analyze`")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    communities = frame.astype(object).where(pd.notna(frame), None).to_dict("records")
    members_path = INTERIM_DIR / "analysis" / "community_members.csv"
    members = pd.read_csv(members_path, encoding="utf-8-sig").to_dict("records") if members_path.exists() else []
    manifest_path = INTERIM_DIR / "analysis" / "analysis_manifest.json"
    graph_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("graph_version", "unknown") if manifest_path.exists() else "unknown"
    driver = connect()
    try:
        with driver.session() as session:
            current_version, _, _ = analysis._graph_version(session)
            if current_version != graph_version:
                raise RuntimeError(f"Neo4j graph={current_version}, analysis graph={graph_version}; chạy `analyze` lại trước khi xuất cộng đồng")
            for community in communities:
                cid = community.get("community")
                if cid is not None:
                    cid = int(cid)
                community_members = [m for m in members if str(m.get("community")) == str(cid)]
                evidence = [r.data() for r in session.run("""
                    MATCH (a:Entity)-[r]-(b:Entity)
                    WHERE (a.community=$community OR b.community=$community) AND a.entity_id < b.entity_id
                    MATCH (ev:Evidence {relation_id:r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
                    RETURN DISTINCT ev.evidence_id AS source_id,ev.quote AS text,d.title AS title,d.url AS url,d.published_at AS published_at
                    ORDER BY d.published_at DESC LIMIT 5
                """, community=cid)]
                community["members"] = [{"entity_id": m.get("entity_id"), "name": m.get("name"), "entity_type": m.get("entity_type")} for m in community_members[:30]]
                community["evidence"] = evidence
    finally:
        driver.close()
    out = INTERIM_DIR / "model_handoff" / "communities_for_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "graph_version": graph_version, "generated_at": now_iso(), "communities": communities}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã xuất cộng đồng cho Huy: {out}")
    return out


def import_community_summaries(path: Path | None = None) -> dict[str, int]:
    package = INTERIM_DIR / "model_handoff" / "communities_for_summary.json"
    path = path or (INTERIM_DIR / "model_handoff" / "community_summaries.jsonl")
    if not package.exists():
        raise FileNotFoundError(f"Chưa có {package}; chạy `stage2 communities-export` trước")
    source_package = json.loads(package.read_text(encoding="utf-8"))
    by_community = {str(c["community"]): {str(e["source_id"]) for e in c.get("evidence", [])} for c in source_package.get("communities", [])}
    if not path.exists():
        raise FileNotFoundError(f"Chưa có kết quả Huy tại {path}")
    rows = []
    seen = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        cid = str(row.get("community_id", ""))
        source_ids = row.get("source_ids")
        if row.get("schema_version") != SCHEMA_VERSION or not row.get("model_version") or not str(row.get("summary", "")).strip():
            raise ValueError(f"Dòng {line_no}: thiếu schema_version/model_version/summary")
        if cid not in by_community or cid in seen:
            raise ValueError(f"Dòng {line_no}: community_id không tồn tại hoặc bị lặp: {cid}")
        if not isinstance(source_ids, list) or not source_ids or not set(map(str, source_ids)).issubset(by_community[cid]):
            raise ValueError(f"Dòng {line_no}: source_ids phải thuộc bằng chứng đã xuất cho community {cid}")
        seen.add(cid)
        rows.append({"community_id": cid, "summary": row["summary"], "source_ids": list(map(str, source_ids)), "model_version": row["model_version"]})
    if not rows:
        raise ValueError("Tệp không có bản tóm tắt nào để nhập")
    driver = connect()
    try:
        with driver.session() as session:
            available = {r["id"] for r in session.run("MATCH (e:Evidence) WHERE e.evidence_id IN $ids RETURN e.evidence_id AS id", ids=sorted({sid for row in rows for sid in row["source_ids"]}))}
            missing = {sid for row in rows for sid in row["source_ids"]} - available
            if missing:
                raise ValueError(f"Bằng chứng không còn trong Neo4j: {sorted(missing)[:10]}")
            session.run("""
                UNWIND $rows AS row
                MERGE (s:CommunitySummary {community_id:row.community_id, graph_version:$graph_version})
                SET s.summary=row.summary,s.source_ids=row.source_ids,s.model_version=row.model_version,s.updated_at=$updated_at,s.schema_version=$schema_version
            """, rows=rows, graph_version=source_package.get("graph_version", "unknown"), updated_at=now_iso(), schema_version=SCHEMA_VERSION).consume()
    finally:
        driver.close()
    result = {"imported": len(rows), "graph_version": source_package.get("graph_version", "unknown")}
    print(f"Đã nhập {len(rows)} tóm tắt cộng đồng có kiểm tra nguồn vào Neo4j.")
    return result
