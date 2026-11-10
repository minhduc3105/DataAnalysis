"""Discover and download reviewable news articles about graph entities."""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from html.parser import HTMLParser
import json
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
import trafilatura

from .common import now_iso, normalize_name
from .config import INTERIM_DIR, PERIOD_END, PERIOD_START, RAW_DIR, ROOT, VN_TZ

WEB_DIR = RAW_DIR / "web"
DB_PATH = WEB_DIR / "crawl.sqlite3"
SOURCES_PATH = ROOT / "seeds" / "web_sources.csv"
DOCS_PATH = INTERIM_DIR / "web_raw_documents.csv"
DISCOVERY_REJECTS_PATH = INTERIM_DIR / "web_discovery_rejected.csv"
DOC_COLUMNS = ["document_id", "url", "resolved_url", "final_url", "source_name", "source_type", "title", "published_at", "published_at_raw", "published_at_source", "published_at_conflict", "collected_at", "content", "raw_html_path", "collection_method", "document_status", "author", "content_hash", "duplicate_content_of", "crawl_relevance_status", "seed_ids"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; VnMusicResearchBot/1.0; +https://example.org/research)"}
TIMEOUT = 25
URL_FILTER_VERSION = "exact-source-url-v2"
MIN_HOST_REQUEST_INTERVAL = 0.25
_HOST_RATE_LOCK = threading.Lock()
_HOST_NEXT_REQUEST = {}
_HOST_SEMAPHORES = {}


def _polite_get(url, **kwargs):
    """Throttle request starts per host while allowing safe cross-host concurrency."""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host:
        with _HOST_RATE_LOCK:
            now = time.monotonic()
            scheduled = max(now, _HOST_NEXT_REQUEST.get(host, now))
            _HOST_NEXT_REQUEST[host] = scheduled + MIN_HOST_REQUEST_INTERVAL
            semaphore = _HOST_SEMAPHORES.get(host)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(2)
                _HOST_SEMAPHORES[host] = semaphore
        delay = scheduled - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        with semaphore:
            return requests.get(url, **kwargs)
    return requests.get(url, **kwargs)


def _db():
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    existed = DB_PATH.exists()
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS urls (url TEXT COLLATE BINARY PRIMARY KEY, state TEXT NOT NULL DEFAULT 'discovered', source_kind TEXT NOT NULL DEFAULT '', discovered_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', subject_ids TEXT NOT NULL DEFAULT '', source_name TEXT NOT NULL DEFAULT '', query TEXT NOT NULL DEFAULT '', resolved_url TEXT NOT NULL DEFAULT '', final_url TEXT NOT NULL DEFAULT '', resolution_state TEXT NOT NULL DEFAULT 'pending', exclusion_reason TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS url_provenance (url TEXT NOT NULL, source_kind TEXT NOT NULL, subject_ids TEXT NOT NULL DEFAULT '', source_name TEXT NOT NULL DEFAULT '', query TEXT NOT NULL DEFAULT '', discovered_at TEXT NOT NULL DEFAULT '', UNIQUE(url,source_kind,subject_ids,query))")
    db.execute("CREATE TABLE IF NOT EXISTS discovery_rejections (url TEXT NOT NULL, query TEXT NOT NULL, reason TEXT NOT NULL, discovered_at TEXT NOT NULL, PRIMARY KEY(url,query))")
    db.execute("CREATE TABLE IF NOT EXISTS discovery_events (event_id INTEGER PRIMARY KEY, url TEXT NOT NULL DEFAULT '', source_kind TEXT NOT NULL, query TEXT NOT NULL DEFAULT '', subject_ids TEXT NOT NULL DEFAULT '', published_at TEXT NOT NULL DEFAULT '', period_status TEXT NOT NULL DEFAULT 'unknown', outcome TEXT NOT NULL, discovered_at TEXT NOT NULL)")
    event_columns = {row[1] for row in db.execute("PRAGMA table_info(discovery_events)")}
    if "period_status" not in event_columns:
        backup = DB_PATH.with_name(f"crawl.schema-backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3")
        target = sqlite3.connect(backup)
        db.backup(target)
        target.close()
        db.execute("ALTER TABLE discovery_events ADD COLUMN period_status TEXT NOT NULL DEFAULT 'unknown'")
    # Existing databases predate the provenance columns.
    columns = {row[1] for row in db.execute("PRAGMA table_info(urls)")}
    additions = (("subject_ids", "TEXT NOT NULL DEFAULT ''"), ("source_name", "TEXT NOT NULL DEFAULT ''"), ("query", "TEXT NOT NULL DEFAULT ''"), ("source_kind", "TEXT NOT NULL DEFAULT ''"), ("resolved_url", "TEXT NOT NULL DEFAULT ''"), ("final_url", "TEXT NOT NULL DEFAULT ''"), ("resolution_state", "TEXT NOT NULL DEFAULT 'pending'"), ("exclusion_reason", "TEXT NOT NULL DEFAULT ''"), ("attempts", "INTEGER NOT NULL DEFAULT 0"))
    missing = [(name, kind) for name, kind in additions if name not in columns]
    if missing:
        # Back up the live SQLite database before changing an existing schema.
        if existed and columns:
            backup = DB_PATH.with_name(f"crawl.schema-backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3")
            target = sqlite3.connect(backup)
            db.backup(target)
            target.close()
        for name, kind in missing:
            db.execute(f"ALTER TABLE urls ADD COLUMN {name} {kind}")
    if "entity_ids" in columns:
        db.execute("UPDATE urls SET subject_ids=replace(entity_ids,'|',',') WHERE subject_ids=''")
    db.commit()
    return db


def _sources():
    if not SOURCES_PATH.exists():
        return []
    with SOURCES_PATH.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("enabled", "yes").strip().lower() in {"yes", "y", "true", "1"}]


def _entities():
    path = INTERIM_DIR / "graph" / "entities.csv"
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        return [dict(entity_id=r.get("entity_id", ""), entity_type=r.get("entity_type", ""), canonical_name=r.get("canonical_name", ""), aliases=r.get("aliases", ""), verification_status=r.get("verification_status", ""), n_documents=r.get("n_documents", "0"), n_relations=r.get("n_relations", "0"), seed_id=r.get("seed_id", "")) for r in rows]
    from .common import read_seeds
    return [dict(entity_id=r["seed_id"], entity_type=r["entity_type"], canonical_name=r["name"], aliases=r.get("aliases", ""), verification_status=r.get("verification_status", ""), n_documents="0", n_relations="0", seed_id=r["seed_id"]) for r in read_seeds()]


def _terms(entities):
    rows = []
    for e in entities:
        eid = e.get("entity_id", "")
        for name in [e.get("canonical_name", ""), *re.split(r"[|;,]", e.get("aliases", ""))]:
            name = " ".join(name.split())
            if len(name) >= 2:
                rows.append((eid, name, normalize_name(name)))
    return list(dict.fromkeys(rows))


def _matcher(terms):
    return terms


def _matches(text, matcher, allow_single_word=False):
    norm = normalize_name(text)
    found = []
    for eid, name, key in matcher:
        if (allow_single_word or len(key.split()) > 1) and key and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", norm):
            found.append(eid)
    return list(dict.fromkeys(found))


def _lead_text(content, max_chars=1200):
    """Return the opening portion used for relevance checks and review."""
    return re.sub(r"\s+", " ", str(content or "")).strip()[:max_chars]


def _source_for_url(url, sources=None):
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        host = ""
    for source in (_sources() if sources is None else sources):
        site = urllib.parse.urlparse(source.get("site_url", "")).hostname or ""
        site = site.lower().removeprefix("www.")
        if site and (host == site or host.endswith("." + site)):
            return source
    return {"source_name": host or "không rõ", "source_type": "website chưa xác minh", "site_url": f"https://{host}" if host else ""}


def _is_article_url(url):
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path.lower()
    if p.scheme not in {"http", "https"} or not host or host.endswith(("wikipedia.org", "wikidata.org")):
        return False
    if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".mp4", ".mp3", ".xml", ".css", ".js")):
        return False
    if path in {"", "/"} or re.search(r"/(rss|tag|tags|category|chuyen-muc|author|search)(/|$)", path):
        return False
    return True


def _date(value):
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(VN_TZ)
        return parsed.date().isoformat()
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(value)[:19], fmt).date().isoformat()
            except ValueError:
                pass
    return ""


def _period_status(published, start, end):
    if not published:
        return "unknown"
    return "in_period" if start.isoformat() <= published <= end.isoformat() else "out_of_period"


def _page_publication_dates(html):
    candidates = []
    class DateParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.dates = []
            self.in_jsonld = False
            self.jsonld = []

        def handle_starttag(self, tag, attrs):
            attrs = {key.lower(): value or "" for key, value in attrs}
            if tag.lower() == "meta":
                key = (attrs.get("property") or attrs.get("name") or "").lower()
                if key in {"article:published_time", "og:published_time", "pubdate", "publishdate"}:
                    self.dates.append((attrs.get("content", ""), "meta:published"))
            elif tag.lower() == "time" and attrs.get("datetime"):
                self.dates.append((attrs["datetime"], "html:time"))
            elif tag.lower() == "script" and "ld+json" in attrs.get("type", "").lower():
                self.in_jsonld = True

        def handle_endtag(self, tag):
            if tag.lower() == "script":
                self.in_jsonld = False

        def handle_data(self, data):
            if self.in_jsonld:
                self.jsonld.append(data)

    parser = DateParser()
    # Publication metadata is in the document head; cap work on large article bodies.
    parser.feed((html or "")[:100_000])
    for raw, source in parser.dates:
        d = _date(raw)
        if d:
            candidates.append((d, source, raw))
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() == "datepublished" and isinstance(child, str):
                    d = _date(child)
                    if d:
                        candidates.append((d, "json-ld:datePublished", child))
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for block in parser.jsonld:
        try:
            visit(json.loads(block))
        except (json.JSONDecodeError, RecursionError):
            continue
    distinct = {d for d, _, _ in candidates}
    if len(distinct) > 1:
        return candidates[0][2], ",".join(sorted({s for _, s, _ in candidates})), "", "ngày đăng mâu thuẫn: " + ",".join(sorted(distinct))
    if not candidates:
        return "", "", "", ""
    d, source, raw = candidates[0]
    return raw, source, d, ""


def _read_docs():
    rows = {}
    legacy = WEB_DIR / "documents.jsonl"
    if legacy.exists():
        with legacy.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if row.get("document_id"):
                        rows[row["document_id"]] = row
                except json.JSONDecodeError:
                    continue
    if DOCS_PATH.exists():
        with DOCS_PATH.open(encoding="utf-8-sig", newline="") as f:
            rows.update({r["document_id"]: r for r in csv.DictReader(f) if r.get("document_id")})
    return list(rows.values())


def _save_docs(rows):
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    if DOCS_PATH.exists():
        with DOCS_PATH.open(encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), [])
        if header != DOC_COLUMNS:
            old = {r.get("document_id"): r for r in _read_docs()}
            old.update({r["document_id"]: r for r in rows})
            with DOCS_PATH.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=DOC_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(old.values())
            return
        mode = "a"
        encoding = "utf-8"
    else:
        mode = "w"
        encoding = "utf-8-sig"
    with DOCS_PATH.open(mode, encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DOC_COLUMNS, extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
        writer.writerows(rows)


def _add_url(db, url, source_kind, subject_ids="", source_name="", query="", published_at="", period_status="unknown"):
    # Preserve the exact URL string supplied by RSS/XML or the user.
    url = "" if url is None else str(url)
    now = now_iso()
    if not url:
        db.execute("INSERT INTO discovery_events(url,source_kind,query,subject_ids,published_at,period_status,outcome,discovered_at) VALUES(?,?,?,?,?,?,?,?)", ("", source_kind, query, subject_ids, published_at, period_status, "missing_url", now))
        return "missing_url"
    try:
        parsed = urllib.parse.urlparse(url)
        valid_http = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        host = (parsed.hostname or "").lower()
    except ValueError:
        valid_http, host = False, ""
    out_of_scope = host in {"wikipedia.org", "wikidata.org"} or host.endswith((".wikipedia.org", ".wikidata.org"))
    reason = "out_of_scope_source" if out_of_scope else ("invalid_http_url" if not valid_http else "")
    state = "out_of_scope" if out_of_scope else ("invalid_url" if not valid_http else "discovered")
    values = {"url": url, "state": state, "source_kind": source_kind, "source_name": source_name or _source_for_url(url).get("source_name", ""), "discovered_at": now, "updated_at": now, "subject_ids": subject_ids, "query": query, "error": "", "attempts": 0, "entity_ids": subject_ids, "resolution_state": "pending", "exclusion_reason": reason}
    columns = {row[1] for row in db.execute("PRAGMA table_info(urls)")}
    selected = {key: value for key, value in values.items() if key in columns}
    names = list(selected)
    result = db.execute(f"INSERT INTO urls({','.join(names)}) VALUES({','.join('?' for _ in names)}) ON CONFLICT(url) DO NOTHING", tuple(selected.values()))
    provenance_values = {"url": url, "provenance_key": hashlib.sha256(f"{source_kind}|{subject_ids}|{query}".encode()).hexdigest(), "source_kind": source_kind, "subject_ids": subject_ids, "source_name": values["source_name"], "query": query, "query_text": query, "discovered_at": now, "query_type": "entity" if source_kind == "Google News RSS" else "", "relation_type": "", "query_hash": "", "date_start": "", "date_end": "", "rss_published_at": published_at}
    pcols = {row[1] for row in db.execute("PRAGMA table_info(url_provenance)")}
    pselected = {key: value for key, value in provenance_values.items() if key in pcols}
    pnames = list(pselected)
    db.execute(f"INSERT INTO url_provenance({','.join(pnames)}) VALUES({','.join('?' for _ in pnames)}) ON CONFLICT DO NOTHING", tuple(pselected.values()))
    outcome = "inserted" if result.rowcount == 1 else "exact_duplicate"
    db.execute("INSERT INTO discovery_events(url,source_kind,query,subject_ids,published_at,period_status,outcome,discovered_at) VALUES(?,?,?,?,?,?,?,?)", (url, source_kind, query, subject_ids, published_at, period_status, outcome, now))
    if subject_ids:
        existing = db.execute("SELECT subject_ids FROM urls WHERE url=?", (url,)).fetchone()[0]
        combined = sorted(set(x for x in re.split(r"[,|]", existing) if x) | set(x for x in re.split(r"[,|]", subject_ids) if x))
        db.execute("UPDATE urls SET subject_ids=? WHERE url=?", (",".join(combined), url))
    return outcome


def add_urls(urls, entity_ids=None):
    valid = {e["entity_id"] for e in _entities()}
    entity_ids = entity_ids or []
    unknown = set(entity_ids) - valid
    if unknown:
        raise ValueError("Entity ID không tồn tại: " + ", ".join(sorted(unknown)))
    db = _db()
    counts = {"inserted": 0, "exact_duplicate": 0, "missing_url": 0}
    try:
        for url in urls or []:
            outcome = _add_url(db, url, "manual article URL", ",".join(entity_ids))
            counts[outcome] += 1
        db.commit()
    finally:
        db.close()
    print(f"URL nhập: mới {counts['inserted']}, trùng chính xác {counts['exact_duplicate']}, thiếu link {counts['missing_url']}.")


def _xml_items(url, limit=1000):
    response = _polite_get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    ns = {"a": "http://www.w3.org/2005/Atom", "sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    if root.tag.endswith("rss"):
        for item in root.findall(".//item")[:limit]:
            yield item.findtext("link", ""), item.findtext("pubDate", "")
    else:
        for item in root.findall(".//sm:url", ns)[:limit]:
            yield item.findtext("sm:loc", "", ns), item.findtext("sm:lastmod", "", ns)
        for item in root.findall(".//a:entry", ns)[:limit]:
            link = item.find("a:link", ns)
            yield (link.get("href", "") if link is not None else ""), item.findtext("a:published", "", ns)


def _sitemaps(source):
    base = source.get("site_url", "").rstrip("/")
    robots = requests.get(base + "/robots.txt", headers=HEADERS, timeout=TIMEOUT)
    robots.raise_for_status()
    found = re.findall(r"(?im)^sitemap:\s*(\S+)", robots.text)
    return found or [base + "/sitemap.xml"]


def _sitemap_urls(source, limit, error_log=None):
    pending = list(_sitemaps(source))
    seen, yielded = set(), 0
    while pending and yielded < limit:
        sitemap = pending.pop(0)
        if sitemap in seen:
            continue
        seen.add(sitemap)
        try:
            response = requests.get(sitemap, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            if root.tag.endswith("sitemapindex"):
                pending.extend(node.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc", "") for node in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap"))
            else:
                for url, modified in _xml_items(sitemap, limit - yielded):
                    yield url, modified
                    yielded += 1
                    if yielded >= limit:
                        break
        except Exception as exc:
            if error_log is not None:
                error_log.append((sitemap, str(exc)))
            print(f"Sitemap lỗi {sitemap}: {exc}")


def _query_jobs(entity_ids=None, date_from=None, date_to=None):
    # Chỉ dùng các loại thực thể cần tìm bài báo: nghệ sĩ, nhóm nhạc và chương trình.
    entities = [e for e in _entities() if e.get("entity_type") in {"Person", "Group", "Show"}]

    # Xếp đối tượng quan trọng lên trước để các lượt chạy có giới hạn query
    # ưu tiên nghệ sĩ/show đã có trong seeds, đã xác minh và có nhiều quan hệ.
    type_order = {"Person": 0, "Group": 1, "Show": 2}

    def priority(entity):
        try:
            degree = int(entity.get("n_relations", 0) or 0)
        except (TypeError, ValueError):
            degree = 0
        return (type_order.get(entity.get("entity_type"), 9), 0 if entity.get("seed_id") else 1,
                0 if entity.get("verification_status") == "đã xác minh" else 1,
                -degree, entity.get("canonical_name", ""))

    entities.sort(key=priority)

    # Nếu người dùng chỉ định ID, giữ lại đúng những thực thể được yêu cầu.
    if entity_ids:
        wanted = set(entity_ids)
        entities = [e for e in entities if e["entity_id"] in wanted]

    # Gom tên chuẩn và alias theo entity_id để có thể tìm bằng nhiều cách viết.
    terms = _terms(entities)
    aliases = {}
    for eid, name, _ in terms:
        aliases.setdefault(eid, []).append(name)

    # Dùng kỳ ngày người dùng truyền vào; nếu bỏ trống thì dùng toàn kỳ của dự án.
    start = date.fromisoformat(date_from) if date_from else PERIOD_START
    end = date.fromisoformat(date_to) if date_to else PERIOD_END
    jobs = []

    # Một query cho mỗi entity trên toàn khoảng ngày, không chia nhỏ theo năm.
    # Như vậy lượt giới hạn phủ nhiều entity hơn và tổng số query giảm mạnh.
    q_after = start - timedelta(days=1)
    q_before = end + timedelta(days=1)
    for e in entities:
        # names gồm tên chuẩn và alias; nếu chưa có alias thì chỉ tìm tên chuẩn.
        names = aliases.get(e["entity_id"], [e["canonical_name"]])

        # Tìm tên chuẩn và tối đa hai alias. Không ép thêm từ khóa chủ đề,
        # vì có thể làm mất bài; mức liên quan sẽ được kiểm tra sau khi tải.
        name_query = " OR ".join(f'"{name}"' for name in names[:3])
        q = f'({name_query}) after:{q_after.isoformat()} before:{q_before.isoformat()}'

        # Mỗi job gắn query với entity để khi có URL, crawler biết query
        # phục vụ đối tượng nào. Hàm chỉ tạo danh sách; discover() mới chạy nó.
        jobs.append((e["entity_id"], q))

    # Mỗi phần tử có dạng (entity_id, chuỗi query Google News).
    return jobs


def discover(entity_ids=None, limit_per_source=1000, search_limit=50, dry_run=False, date_from=None, date_to=None, force=False):
    start = date.fromisoformat(date_from) if date_from else PERIOD_START
    end = date.fromisoformat(date_to) if date_to else PERIOD_END
    if start < PERIOD_START or end > PERIOD_END or start > end:
        raise ValueError(f"Khoảng ngày phải nằm trong {PERIOD_START}–{PERIOD_END}")
    jobs = _query_jobs(entity_ids, start.isoformat(), end.isoformat())
    all_jobs = jobs
    if dry_run:
        jobs = jobs[:max(0, search_limit)]
        print(f"Dry-run: lượt này {len(jobs)} query; toàn bộ kế hoạch {len(all_jobs)} query/entity; chưa gọi mạng hoặc ghi checkpoint.")
        for eid, query in jobs:
            print(f"  {eid}: {query}")
        print(f"TỔNG: {len(all_jobs)} query/entity trong kế hoạch; {len(jobs)} query được chọn cho lượt này.")
        return
    db = _db()
    try:
        # Due jobs are rechecked after 30 days; never repeat an already-finished query every run.
        db.execute("CREATE TABLE IF NOT EXISTS queries (query TEXT PRIMARY KEY, entity_id TEXT, state TEXT, checked_at TEXT, error TEXT DEFAULT '')")
        qcols = {row[1] for row in db.execute("PRAGMA table_info(queries)")}
        if "filter_version" not in qcols:
            backup = DB_PATH.with_name(f"crawl.schema-backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3")
            target = sqlite3.connect(backup)
            db.backup(target)
            target.close()
            db.execute("ALTER TABLE queries ADD COLUMN filter_version TEXT NOT NULL DEFAULT ''")
        # Queries from earlier yearly plans are superseded by each entity's new
        # full-period query. Keep checkpoints only when the exact query recurs.
        recent = {row[0] for row in db.execute("SELECT query FROM queries WHERE state='done' AND filter_version=? AND checked_at >= datetime('now','-30 days')", (URL_FILTER_VERSION,))}
        if not force:
            jobs = [job for job in jobs if job[1] not in recent]
        jobs = jobs[:max(0, search_limit)]
        errors = rss_errors = google_errors = 0
        rss_results = rss_added = rss_duplicates = rss_missing = rss_out_of_range = 0
        sitemap_results = sitemap_added = sitemap_duplicates = sitemap_missing = 0
        sitemap_error_log = []
        query_results = google_added = duplicate_results = out_of_range = invalid_results = 0
        for source in _sources():
            feed = source.get("feed_url", "").strip()
            if feed:
                try:
                    for url, published in _xml_items(feed, limit_per_source):
                        rss_results += 1
                        d = _date(published)
                        if d and not start.isoformat() <= d <= end.isoformat():
                            rss_out_of_range += 1
                        outcome = _add_url(db, url, "RSS", "", source.get("source_name", ""), feed, d, _period_status(d, start, end))
                        rss_added += outcome == "inserted"
                        rss_duplicates += outcome == "exact_duplicate"
                        rss_missing += outcome == "missing_url"
                    db.commit()
                except Exception as exc:
                    errors += 1
                    rss_errors += 1
                    print(f"RSS lỗi {source.get('source_name')}: {exc}")
            # Sitemap lastmod is only a discovery hint; publication date is verified from article HTML.
            if not date_from and not date_to:
                try:
                    for url, _modified in _sitemap_urls(source, limit_per_source, sitemap_error_log):
                        sitemap_results += 1
                        outcome = _add_url(db, url, "sitemap", "", source.get("source_name", ""), "sitemap")
                        sitemap_added += outcome == "inserted"
                        sitemap_duplicates += outcome == "exact_duplicate"
                        sitemap_missing += outcome == "missing_url"
                except Exception as exc:
                    sitemap_error_log.append((source.get("source_name", ""), str(exc)))
                    print(f"Sitemap lỗi {source.get('source_name')}: {exc}")
                db.commit()
        for i, (eid, query) in enumerate(jobs, 1):
            url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=vi&gl=VN&ceid=VN:vi"
            try:
                db.execute("SAVEPOINT query_batch")
                query_new = query_duplicates = query_missing = 0
                for article_url, published in _xml_items(url, 100):
                    query_results += 1
                    d = _date(published)
                    if d and not start.isoformat() <= d <= end.isoformat():
                        out_of_range += 1
                    outcome = _add_url(db, article_url, "Google News RSS", eid, "Google News", query, d, _period_status(d, start, end))
                    query_new += outcome == "inserted"
                    query_duplicates += outcome == "exact_duplicate"
                    query_missing += outcome == "missing_url"
                db.execute("RELEASE query_batch")
                db.execute("INSERT OR REPLACE INTO queries(query,entity_id,state,checked_at,error,filter_version) VALUES(?,?,?,?,?,?)", (query, eid, "done", datetime.now(timezone.utc).isoformat(), "", URL_FILTER_VERSION))
                db.commit()
                google_added += query_new
                duplicate_results += query_duplicates
                invalid_results += query_missing
            except Exception as exc:
                errors += 1
                google_errors += 1
                try:
                    db.execute("ROLLBACK TO query_batch")
                    db.execute("RELEASE query_batch")
                except sqlite3.OperationalError:
                    pass
                db.execute("INSERT OR REPLACE INTO queries(query,entity_id,state,checked_at,error,filter_version) VALUES(?,?,?,?,?,?)", (query, eid, "error", datetime.now(timezone.utc).isoformat(), str(exc)[:500], URL_FILTER_VERSION))
                db.commit()
            if i % 10 == 0:
                db.commit()
                print(f"Đã chạy {i}/{len(jobs)} query; Google News trả {query_results}, URL mới {google_added}, trùng chính xác {duplicate_results}, thiếu URL {invalid_results}, ngoài kỳ theo RSS {out_of_range}; RSS mới {rss_added}.")
            time.sleep(0.2)
        db.commit()
        report = {"planned": len(jobs), "rss_results": rss_results, "rss_new_urls": rss_added, "rss_duplicates": rss_duplicates, "rss_missing_urls": rss_missing, "rss_out_of_period": rss_out_of_range, "rss_errors": rss_errors, "sitemap_results": sitemap_results, "sitemap_new_urls": sitemap_added, "sitemap_duplicates": sitemap_duplicates, "sitemap_missing_urls": sitemap_missing, "sitemap_errors": len(sitemap_error_log), "google_news_results": query_results, "google_news_new_urls": google_added, "google_news_duplicates": duplicate_results, "google_news_missing_urls": invalid_results, "google_news_out_of_period": out_of_range, "google_news_errors": google_errors, "errors": errors + len(sitemap_error_log), "period": [start.isoformat(), end.isoformat()], "checked_at": now_iso()}
        INTERIM_DIR.mkdir(parents=True, exist_ok=True)
        (INTERIM_DIR / "web_search_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        rejects = db.execute("SELECT url,query,reason,discovered_at FROM discovery_rejections ORDER BY discovered_at").fetchall()
        with DISCOVERY_REJECTS_PATH.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["url", "query", "reason", "discovered_at"])
            writer.writerows(rejects)
        print(f"Tìm xong: RSS mới {rss_added}, trùng chính xác {rss_duplicates}, thiếu URL {rss_missing}; sitemap mới {sitemap_added}, trùng chính xác {sitemap_duplicates}, thiếu URL {sitemap_missing}; Google News mới {google_added}, trùng chính xác {duplicate_results}, thiếu URL {invalid_results}; lỗi {errors + len(sitemap_error_log)}. Xem data/interim/web_search_report.json")
    except KeyboardInterrupt:
        # Every completed query has committed its URLs and checkpoint atomically.
        try:
            try:
                db.execute("ROLLBACK TO query_batch")
                db.execute("RELEASE query_batch")
            except sqlite3.OperationalError:
                # The interrupt may have happened between queries or in RSS discovery.
                pass
            db.commit()
            interim = {"interrupted": True, "planned": len(jobs), "google_news_results": query_results,
                       "google_news_new_urls": google_added, "google_news_duplicates": duplicate_results,
                       "google_news_missing_urls": invalid_results, "google_news_errors": google_errors,
                       "rss_results": rss_results, "rss_new_urls": rss_added, "rss_duplicates": rss_duplicates,
                       "rss_missing_urls": rss_missing, "rss_errors": rss_errors,
                       "errors": errors, "period": [start.isoformat(), end.isoformat()], "checked_at": now_iso()}
            INTERIM_DIR.mkdir(parents=True, exist_ok=True)
            (INTERIM_DIR / "web_search_report.json").write_text(json.dumps(interim, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Đã dừng; query hoàn tất đã được lưu. Query đang chạy sẽ được thử lại. Tiến độ ở data/interim/web_search_report.json")
        except Exception:
            db.rollback()
        raise
    finally:
        db.close()


def _resolve_news_url(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host != "news.google.com":
        return url
    response = _polite_get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    match = re.search(r'(?:url|article_url)=([^&" ]+)', response.url + " " + response.text[:20000], re.I)
    if match:
        candidate = urllib.parse.unquote(match.group(1)).replace("&amp;", "&")
        candidate_host = (urllib.parse.urlparse(candidate).hostname or "").lower()
        if urllib.parse.urlparse(candidate).scheme in {"http", "https"} and candidate_host and candidate_host != "news.google.com":
            return candidate
    if (urllib.parse.urlparse(response.url).hostname or "").lower() != "news.google.com":
        return response.url
    raise ValueError("chưa giải được URL bài gốc từ Google News")


def _extract_page(url, entity_ids, matcher=None, matcher_by_id=None):
    response = _polite_get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    html = response.text
    raw, date_source, published, conflict = _page_publication_dates(html)
    downloaded = trafilatura.extract(html, include_comments=False, include_tables=True, output_format="txt") or ""
    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title if metadata else "") or ""
    author = (metadata.author if metadata else "") or ""
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    if len(downloaded) < 120:
        raise ValueError("không trích xuất được nội dung bài đủ dài")
    if matcher_by_id is not None and entity_ids:
        candidate_terms = [term for entity_id in entity_ids for term in matcher_by_id.get(entity_id, ())]
    elif matcher is not None:
        candidate_terms = matcher
    else:
        entities = _entities()
        candidate_terms = _terms([e for e in entities if not entity_ids or e["entity_id"] in entity_ids])
    matches = _matches(title + "\n" + downloaded, candidate_terms)
    relevance = "liên quan" if matches else "cần duyệt liên quan"
    return response.url, html, title, author, raw, date_source, published, conflict, downloaded, relevance, matches


def _fetch_crawl_item(original, previously_resolved, subjects, source_name, source_kind, allow_resolve, matcher, matcher_by_id, sources):
    """Fetch one URL without touching SQLite; callers persist results serially."""
    ids = [x for x in re.split(r"[,|]", subjects) if x]
    url = previously_resolved or original
    resolved_new = False
    try:
        parsed = urllib.parse.urlparse(original)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("URL không phải HTTP/HTTPS hợp lệ")
        if (parsed.hostname or "").lower() == "news.google.com":
            if previously_resolved:
                url = previously_resolved
            elif not allow_resolve:
                return {"kind": "pending", "original": original}
            else:
                url = _resolve_news_url(original)
                resolved_new = True
        else:
            url = original
        source = _source_for_url(url, sources)
        final, html, title, author, raw, date_source, published, conflict, content, relevance, matched = _extract_page(url, ids, matcher, matcher_by_id)
        return {"kind": "downloaded", "original": original, "url": url, "final": final, "ids": ids,
                "source": source, "source_name": source_name, "source_kind": source_kind,
                "html": html, "title": title, "author": author, "raw": raw,
                "date_source": date_source, "published": published, "conflict": conflict,
                "content": content, "relevance": relevance, "matched": matched,
                "resolved_new": resolved_new}
    except Exception as exc:
        try:
            original_host = (urllib.parse.urlparse(original).hostname or "").lower()
        except ValueError:
            original_host = ""
        return {"kind": "error", "original": original, "error": str(exc)[:500],
                "resolved_url": url if url != original else "",
                "resolved_new": resolved_new,
                "resolution_state": ("resolved" if previously_resolved or url != original else "error") if original_host == "news.google.com" else "pending"}


def crawl(limit=None, entity_ids=None, resolve_limit=50, workers=8):
    db = _db()
    accepted = review = out_period = errors = downloaded = resolved = 0
    try:
        rows = db.execute("SELECT url,resolved_url,subject_ids,source_name,source_kind FROM urls WHERE state IN ('discovered','error') ORDER BY discovered_at LIMIT ?", (limit or -1,)).fetchall()
        entities = [e for e in _entities() if not entity_ids or e["entity_id"] in entity_ids]
        matcher = _terms(entities)
        matcher_by_id = {}
        for term in matcher:
            matcher_by_id.setdefault(term[0], []).append(term)
        sources = _sources()
        content_owner = {r.get("content_hash"): r.get("document_id") for r in _read_docs() if r.get("content_hash") and r.get("document_id")}
        tasks = []
        resolve_budget = max(0, resolve_limit)
        for original, previously_resolved, subjects, source_name, source_kind in rows:
            ids = [x for x in re.split(r"[,|]", subjects) if x]
            if entity_ids and ids and not set(ids).intersection(entity_ids):
                continue
            try:
                host = (urllib.parse.urlparse(original).hostname or "").lower()
            except ValueError:
                host = ""
            needs_resolve = host == "news.google.com" and not previously_resolved
            allow_resolve = not needs_resolve or resolve_budget > 0
            if needs_resolve and allow_resolve:
                resolve_budget -= 1
            tasks.append((original, previously_resolved, subjects, source_name, source_kind, allow_resolve))

        chunk_size = max(1, max(1, workers) * 4)
        records = []
        processed = 0
        print(f"Bắt đầu crawl {len(tasks)} URL; workers={max(1, workers)}, giới hạn giải Google News={max(0, resolve_limit)}.", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for offset in range(0, len(tasks), chunk_size):
                chunk = tasks[offset:offset + chunk_size]
                futures = [pool.submit(_fetch_crawl_item, *task, matcher, matcher_by_id, sources) for task in chunk]
                for future in as_completed(futures):
                    result = future.result()
                    processed += 1
                    original = result["original"]
                    if result["kind"] == "pending":
                        db.execute("UPDATE urls SET resolution_state='pending',error='đợi lượt giải URL Google News' WHERE url=?", (original,))
                    elif result["kind"] == "error":
                        errors += 1
                        resolved += bool(result.get("resolved_new"))
                        db.execute("UPDATE urls SET state='error',resolved_url=CASE WHEN ?='' THEN resolved_url ELSE ? END,updated_at=?,error=?,exclusion_reason=?,resolution_state=?,attempts=attempts+1 WHERE url=?", (result["resolved_url"], result["resolved_url"], now_iso(), result["error"], result["error"], result["resolution_state"], original))
                    else:
                        resolved += bool(result.get("resolved_new"))
                        url, final = result["url"], result["final"]
                        ids, source = result["ids"], result["source"]
                        title, author, raw = result["title"], result["author"], result["raw"]
                        date_source, published = result["date_source"], result["published"]
                        conflict, content = result["conflict"], result["content"]
                        relevance, matched, html = result["relevance"], result["matched"], result["html"]
                        raw_path = WEB_DIR / "html" / (hashlib.sha256(original.encode()).hexdigest() + ".html")
                        raw_path.parent.mkdir(parents=True, exist_ok=True)
                        raw_path.write_text(html, encoding="utf-8")
                        d = date.fromisoformat(published) if published else None
                        if d and not (PERIOD_START <= d <= PERIOD_END):
                            state, status = "out_of_period", "loại bỏ"
                            out_period += 1
                        elif not d or conflict or relevance != "liên quan" or not _is_article_url(final):
                            state, status = "needs_review", "cần kiểm tra"
                            review += 1
                        else:
                            state, status = "crawled", "hợp lệ"
                            accepted += 1
                        docid = "DOC_WEB_" + hashlib.sha256(original.encode()).hexdigest()[:20]
                        content_hash = hashlib.sha256(content.encode()).hexdigest()
                        duplicate_of = content_owner.get(content_hash, "")
                        if duplicate_of == docid:
                            duplicate_of = ""
                        content_owner.setdefault(content_hash, docid)
                        records.append({"document_id": docid, "url": original, "resolved_url": url, "final_url": final, "source_name": source.get("source_name") or result["source_name"], "source_type": source.get("source_type", "website chưa xác minh"), "title": title, "published_at": published, "published_at_raw": raw, "published_at_source": date_source, "published_at_conflict": conflict, "collected_at": now_iso(), "content": content, "raw_html_path": str(raw_path.relative_to(ROOT)), "collection_method": result["source_kind"] or "web", "document_status": status, "author": author, "content_hash": content_hash, "duplicate_content_of": duplicate_of, "crawl_relevance_status": relevance, "seed_ids": ",".join(sorted(set(ids + matched)))})
                        review_reason = "đích tải không có dạng bài viết thông thường" if not _is_article_url(final) else "cần kiểm tra ngày/nội dung/liên quan"
                        db.execute("UPDATE urls SET state=?,resolved_url=?,final_url=?,updated_at=?,error='',resolution_state='resolved',exclusion_reason=? WHERE url=?", (state, url, final, now_iso(), "ngoài kỳ" if state == "out_of_period" else (review_reason if state == "needs_review" else ""), original))
                        downloaded += 1
                    if processed % 10 == 0 or processed == len(tasks):
                        print(f"Tiến độ crawl: {processed}/{len(tasks)}; tải được {downloaded}, lỗi {errors}, Google News đã giải {resolved}.", flush=True)
                if records:
                    _save_docs(records)
                    records.clear()
                db.commit()
        db.commit()
        report = {"processed_this_run": processed, "downloaded_this_run": downloaded, "google_candidates_resolved": resolved, "accepted_this_run": accepted, "needs_review_this_run": review, "out_of_period_this_run": out_period, "errors_this_run": errors, "workers": max(1, workers)}
        INTERIM_DIR.mkdir(parents=True, exist_ok=True)
        (INTERIM_DIR / "web_crawl_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Tải xong: {downloaded} trang; hợp lệ {accepted}, chờ duyệt {review}, ngoài kỳ {out_period}, lỗi {errors}.")
    finally:
        db.close()


def sources_check():
    results = []
    for source in _sources():
        for kind, url in (("RSS", source.get("feed_url", "")), ("robots", source.get("site_url", "").rstrip("/") + "/robots.txt")):
            if not url:
                continue
            try:
                response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
                results.append((source.get("source_name"), kind, response.status_code, "OK" if response.ok else "HTTP lỗi"))
            except requests.RequestException as exc:
                results.append((source.get("source_name"), kind, "lỗi", str(exc)[:120]))
    for row in results:
        print(" | ".join(map(str, row)))


def clean():
    from . import web_clean
    web_clean.clean()


def review_export():
    path = INTERIM_DIR / "web_candidates.csv"
    if not path.exists():
        path.write_text("url,title,published_at,source_name,entity_id,review_status\n", encoding="utf-8-sig")
    print(f"Bảng ứng viên: {path}")


def review_import():
    path = INTERIM_DIR / "web_candidates.csv"
    if not path.exists():
        print("Chưa có web_candidates.csv")
        return
    db = _db()
    inserted = duplicates = missing = 0
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("url"):
                    outcome = _add_url(db, row["url"], "Google News review", row.get("entity_id", ""), row.get("source_name", ""), row.get("title", ""))
                    inserted += outcome == "inserted"
                    duplicates += outcome == "exact_duplicate"
                    missing += outcome == "missing_url"
        db.commit()
    finally:
        db.close()
    print(f"URL ứng viên: mới {inserted}, trùng chính xác {duplicates}, thiếu link {missing}.")


def recover_urls(dry_run=False):
    """Restore historical discovery results rejected by the old early URL filter."""
    db = _db()
    try:
        candidates = db.execute("SELECT r.url,r.query,r.reason FROM discovery_rejections r WHERE r.url<>'' ORDER BY r.url,r.discovered_at").fetchall()
        recoverable = [row for row in candidates if db.execute("SELECT 1 FROM urls WHERE url=?", (row[0],)).fetchone() is None]
        if dry_run:
            print(f"Dry-run phục hồi: {len({row[0] for row in recoverable})} URL còn thiếu trong {len({row[0] for row in candidates})} URL lịch sử; chưa ghi dữ liệu.")
            return
        inserted = duplicates = 0
        for url, query, _reason in recoverable:
            outcome = _add_url(db, url, "Google News recovered", "", "Google News", query)
            inserted += outcome == "inserted"
            duplicates += outcome == "exact_duplicate"
        db.commit()
        print(f"Phục hồi xong: {inserted} URL mới, {duplicates} trùng chính xác; chạy lại lệnh sẽ không nhân đôi.")
    finally:
        db.close()


def stats():
    db = _db()
    try:
        by_state = dict(db.execute("SELECT state,COUNT(*) FROM urls GROUP BY state").fetchall())
        print("Tổng URL đầu vào:", db.execute("SELECT COUNT(*) FROM urls").fetchone()[0])
        print("Hàng đợi theo trạng thái:", by_state)
        print("URL theo nguồn:", dict(db.execute("SELECT source_kind,COUNT(*) FROM urls GROUP BY source_kind").fetchall()))
        docs = _read_docs()
        by_doc_status = {}
        for row in docs:
            status = row.get("document_status", "") or "chưa phân loại"
            by_doc_status[status] = by_doc_status.get(status, 0) + 1
        print("Tài liệu thô đã tải:", len(docs), "| trạng thái:", by_doc_status)
    finally:
        db.close()
