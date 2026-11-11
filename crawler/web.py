"""Discover and download reviewable news articles about graph entities."""

from __future__ import annotations

import csv
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
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
DOC_COLUMNS = ["document_id", "url", "resolved_url", "final_url", "source_name", "source_type", "title", "title_source", "abstract", "abstract_source", "rss_abstract", "article_lead", "lead_source", "published_at", "published_at_iso", "published_at_raw", "published_at_source", "published_at_conflict", "collected_at", "content", "raw_html_path", "collection_method", "document_status", "author", "content_hash", "duplicate_content_of", "crawl_relevance_status", "review_reason", "query_entity_ids", "seed_ids"]
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
    db.execute("CREATE TABLE IF NOT EXISTS urls (url TEXT COLLATE BINARY PRIMARY KEY, state TEXT NOT NULL DEFAULT 'discovered', source_kind TEXT NOT NULL DEFAULT '', discovered_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', subject_ids TEXT NOT NULL DEFAULT '', source_name TEXT NOT NULL DEFAULT '', query TEXT NOT NULL DEFAULT '', resolved_url TEXT NOT NULL DEFAULT '', final_url TEXT NOT NULL DEFAULT '', resolution_state TEXT NOT NULL DEFAULT 'pending', exclusion_reason TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0, rss_title TEXT NOT NULL DEFAULT '', rss_abstract TEXT NOT NULL DEFAULT '', rss_published_at TEXT NOT NULL DEFAULT '', rss_source TEXT NOT NULL DEFAULT '')")
    db.execute("CREATE TABLE IF NOT EXISTS url_provenance (url TEXT NOT NULL, source_kind TEXT NOT NULL, subject_ids TEXT NOT NULL DEFAULT '', source_name TEXT NOT NULL DEFAULT '', query TEXT NOT NULL DEFAULT '', discovered_at TEXT NOT NULL DEFAULT '', rss_title TEXT NOT NULL DEFAULT '', rss_abstract TEXT NOT NULL DEFAULT '', rss_published_at TEXT NOT NULL DEFAULT '', rss_source TEXT NOT NULL DEFAULT '', UNIQUE(url,source_kind,subject_ids,query))")
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
    additions = (("subject_ids", "TEXT NOT NULL DEFAULT ''"), ("source_name", "TEXT NOT NULL DEFAULT ''"), ("query", "TEXT NOT NULL DEFAULT ''"), ("source_kind", "TEXT NOT NULL DEFAULT ''"), ("resolved_url", "TEXT NOT NULL DEFAULT ''"), ("final_url", "TEXT NOT NULL DEFAULT ''"), ("resolution_state", "TEXT NOT NULL DEFAULT 'pending'"), ("exclusion_reason", "TEXT NOT NULL DEFAULT ''"), ("attempts", "INTEGER NOT NULL DEFAULT 0"), ("rss_title", "TEXT NOT NULL DEFAULT ''"), ("rss_abstract", "TEXT NOT NULL DEFAULT ''"), ("rss_published_at", "TEXT NOT NULL DEFAULT ''"), ("rss_source", "TEXT NOT NULL DEFAULT ''"))
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
    provenance_columns = {row[1] for row in db.execute("PRAGMA table_info(url_provenance)")}
    provenance_additions = (("rss_title", "TEXT NOT NULL DEFAULT ''"), ("rss_abstract", "TEXT NOT NULL DEFAULT ''"), ("rss_published_at", "TEXT NOT NULL DEFAULT ''"), ("rss_source", "TEXT NOT NULL DEFAULT ''"))
    missing_provenance = [(name, kind) for name, kind in provenance_additions if name not in provenance_columns]
    if missing_provenance:
        if existed and provenance_columns:
            backup = DB_PATH.with_name(f"crawl.schema-backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3")
            target = sqlite3.connect(backup)
            db.backup(target)
            target.close()
        for name, kind in missing_provenance:
            db.execute(f"ALTER TABLE url_provenance ADD COLUMN {name} {kind}")
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


def _relevance_terms(entities):
    """Use multiword aliases plus distinctive single-word names unique in graph."""
    terms = _terms(entities)
    owners = {}
    for eid, _name, key in terms:
        if len(key.split()) == 1 and len(key) >= 5:
            owners.setdefault(key, set()).add(eid)
    return [term for term in terms if len(term[2].split()) > 1 or (len(term[2]) >= 5 and owners.get(term[2]) == {term[0]})]


def _relevance_matches(title, text, matcher):
    """Match phrases anywhere and unique one-word aliases in headline casing."""
    matches = _matches(text, matcher)
    single_terms = [term for term in matcher if len(term[2].split()) == 1]
    for eid, name, _key in single_terms:
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.I | re.UNICODE)
        if any(m.group(0)[:1].isupper() for m in pattern.finditer(title or "")):
            matches.append(eid)
    return list(dict.fromkeys(matches))


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
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    path = p.path.lower()
    if p.scheme not in {"http", "https"} or not host or host in {"news.google.com", "google.com", "www.google.com", "accounts.google.com", "consent.google.com", "wikipedia.org", "wikidata.org"} or host.endswith((".googleusercontent.com", ".wikipedia.org", ".wikidata.org")):
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
        try:
            parsed = parsedate_to_datetime(str(value))
            if parsed.tzinfo:
                parsed = parsed.astimezone(VN_TZ)
            return parsed.date().isoformat()
        except (TypeError, ValueError, OverflowError):
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(value)[:19], fmt).date().isoformat()
            except ValueError:
                pass
    return ""


def _published_iso(value):
    """Keep an ISO timestamp only when its timezone is explicit."""
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.tzinfo is not None else ""
    except ValueError:
        try:
            parsed = parsedate_to_datetime(str(value))
            return parsed.isoformat() if parsed and parsed.tzinfo else ""
        except (TypeError, ValueError, OverflowError):
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
                if key in {"article:published_time", "og:published_time", "pubdate", "publishdate", "datepublished", "date"}:
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
            columns = list(dict.fromkeys(DOC_COLUMNS + [key for row in old.values() for key in row if key not in DOC_COLUMNS]))
            with DOCS_PATH.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(old.values())
            return
        mode = "a"
        encoding = "utf-8"
        with DOCS_PATH.open(encoding="utf-8-sig", newline="") as f:
            existing_ids = {r.get("document_id", "") for r in csv.DictReader(f)}
        rows = [row for row in rows if row.get("document_id") not in existing_ids]
        if not rows:
            return
    else:
        mode = "w"
        encoding = "utf-8-sig"
    with DOCS_PATH.open(mode, encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DOC_COLUMNS, extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
        writer.writerows(rows)


def _add_url(db, url, source_kind, subject_ids="", source_name="", query="", published_at="", period_status="unknown", rss_title="", rss_abstract="", rss_source="", rss_published_at=""):
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
    rss_published_at = rss_published_at or published_at
    values = {"url": url, "state": state, "source_kind": source_kind, "source_name": source_name or _source_for_url(url).get("source_name", ""), "discovered_at": now, "updated_at": now, "subject_ids": subject_ids, "query": query, "error": "", "attempts": 0, "entity_ids": subject_ids, "resolution_state": "pending", "exclusion_reason": reason, "rss_title": rss_title, "rss_abstract": rss_abstract, "rss_published_at": rss_published_at, "rss_source": rss_source}
    columns = {row[1] for row in db.execute("PRAGMA table_info(urls)")}
    selected = {key: value for key, value in values.items() if key in columns}
    names = list(selected)
    result = db.execute(f"INSERT INTO urls({','.join(names)}) VALUES({','.join('?' for _ in names)}) ON CONFLICT(url) DO NOTHING", tuple(selected.values()))
    provenance_values = {"url": url, "provenance_key": hashlib.sha256(f"{source_kind}|{subject_ids}|{query}".encode()).hexdigest(), "source_kind": source_kind, "subject_ids": subject_ids, "source_name": values["source_name"], "query": query, "query_text": query, "discovered_at": now, "query_type": "entity" if source_kind == "Google News RSS" else "", "relation_type": "", "query_hash": "", "date_start": "", "date_end": "", "rss_published_at": rss_published_at, "rss_title": rss_title, "rss_abstract": rss_abstract, "rss_source": rss_source}
    pcols = {row[1] for row in db.execute("PRAGMA table_info(url_provenance)")}
    pselected = {key: value for key, value in provenance_values.items() if key in pcols}
    pnames = list(pselected)
    db.execute(f"INSERT INTO url_provenance({','.join(pnames)}) VALUES({','.join('?' for _ in pnames)}) ON CONFLICT(url,source_kind,subject_ids,query) DO UPDATE SET rss_title=CASE WHEN excluded.rss_title<>'' THEN excluded.rss_title ELSE url_provenance.rss_title END,rss_abstract=CASE WHEN excluded.rss_abstract<>'' THEN excluded.rss_abstract ELSE url_provenance.rss_abstract END,rss_published_at=CASE WHEN excluded.rss_published_at<>'' THEN excluded.rss_published_at ELSE url_provenance.rss_published_at END,rss_source=CASE WHEN excluded.rss_source<>'' THEN excluded.rss_source ELSE url_provenance.rss_source END", tuple(pselected.values()))
    db.execute("UPDATE urls SET rss_title=CASE WHEN rss_title='' THEN ? ELSE rss_title END,rss_abstract=CASE WHEN rss_abstract='' THEN ? ELSE rss_abstract END,rss_published_at=CASE WHEN rss_published_at='' THEN ? ELSE rss_published_at END,rss_source=CASE WHEN rss_source='' THEN ? ELSE rss_source END WHERE url=?", (rss_title, rss_abstract, rss_published_at, rss_source, url))
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


def _plain_xml_text(value):
    class TextParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() in {"p", "div", "br", "li", "section"}:
                self.parts.append(" ")

        def handle_endtag(self, tag):
            if tag.lower() in {"p", "div", "br", "li", "section"}:
                self.parts.append(" ")

        def handle_data(self, data):
            if data:
                self.parts.append(data)

    parser = TextParser()
    parser.feed(value or "")
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def _xml_items(url, limit=1000, include_metadata=False):
    response = _polite_get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    ns = {"a": "http://www.w3.org/2005/Atom", "sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    if root.tag.endswith("rss"):
        for item in root.findall(".//item")[:limit]:
            article_url = item.findtext("link", "")
            published = item.findtext("pubDate", "")
            if include_metadata:
                source = item.findtext("source", "")
                yield (article_url, published, _plain_xml_text(item.findtext("title", "")),
                       _plain_xml_text(item.findtext("description", "")), _plain_xml_text(source))
            else:
                yield article_url, published
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
                for article_url, published, rss_title, rss_abstract, rss_source in _xml_items(url, 100, include_metadata=True):
                    query_results += 1
                    d = _date(published)
                    if d and not start.isoformat() <= d <= end.isoformat():
                        out_of_range += 1
                    outcome = _add_url(db, article_url, "Google News RSS", eid, "Google News", query, d, _period_status(d, start, end), rss_title, rss_abstract, rss_source, published)
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


def _google_news_response(url):
    """Return (publisher URL, response) from a Google News wrapper request."""
    response = _polite_get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"Google News HTTP {response.status_code}; content-type={response.headers.get('Content-Type', '')}; final={response.url}; {exc}") from exc
    match = re.search(r'(?:url|article_url)=([^&" ]+)', response.url + " " + response.text[:20000], re.I)
    if match:
        candidate = urllib.parse.unquote(match.group(1)).replace("&amp;", "&")
        candidate_host = (urllib.parse.urlparse(candidate).hostname or "").lower()
        if urllib.parse.urlparse(candidate).scheme in {"http", "https"} and candidate_host and candidate_host != "news.google.com":
            return candidate, response
    if (urllib.parse.urlparse(response.url).hostname or "").lower() != "news.google.com":
        return response.url, response
    return "", response


def _response_snippet(response, limit=300):
    """Make a short, readable diagnostic from an HTTP response body."""
    text = re.sub(r"<[^>]+>", " ", getattr(response, "text", "") or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _resolve_news_url(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host != "news.google.com":
        return url
    target, _response = _google_news_response(url)
    if target:
        return target
    raise ValueError("chưa giải được URL bài gốc từ Google News")


def _html_metadata(html):
    """Read common title, author, and description fields from HTML metadata."""
    class MetadataParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.meta = {}
            self.title_parts = []
            self.in_title = False

        def handle_starttag(self, tag, attrs):
            attrs = {key.lower(): value or "" for key, value in attrs}
            if tag.lower() == "meta":
                key = (attrs.get("property") or attrs.get("name") or "").lower()
                if key and attrs.get("content"):
                    self.meta.setdefault(key, attrs["content"].strip())
            elif tag.lower() == "title":
                self.in_title = True

        def handle_endtag(self, tag):
            if tag.lower() == "title":
                self.in_title = False

        def handle_data(self, data):
            if self.in_title and data.strip():
                self.title_parts.append(data.strip())

    parser = MetadataParser()
    parser.feed((html or "")[:200_000])
    title = (parser.meta.get("og:title") or parser.meta.get("twitter:title") or " ".join(parser.title_parts)).strip()
    abstract = (parser.meta.get("og:description") or parser.meta.get("description") or parser.meta.get("twitter:description") or "").strip()
    author = (parser.meta.get("author") or parser.meta.get("article:author") or parser.meta.get("parsely-author") or "").strip()
    return title, author, abstract


def _google_news_metadata(html):
    """Extract the headline and short summary exposed by a Google News preview."""
    title, _author, abstract = _html_metadata(html)
    return title, abstract


def _extract_article_fields(html):
    """Extract article-specific fields with provenance, excluding site chrome."""
    class ArticleParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.meta, self.jsonld = {}, []
            self.in_script = False
            self.script_data = []
            self.stack, self.blocks = [], []
            self.current = None
            self.in_h1 = False
            self.h1_parts = []
            self.in_title = False
            self.title_parts = []

        def handle_starttag(self, tag, attrs):
            attrs = {k.lower(): (v or "") for k, v in attrs}
            tag = tag.lower()
            if tag == "meta":
                key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
                if key and attrs.get("content"):
                    self.meta.setdefault(key, attrs["content"].strip())
            if tag == "script" and "ld+json" in attrs.get("type", "").lower():
                self.in_script, self.script_data = True, []
            classes = (attrs.get("class", "") + " " + attrs.get("itemprop", "")).lower()
            blocked = tag in {"nav", "aside", "footer", "header", "form", "button"} or any(x in classes for x in ("advert", "related", "recommend", "menu", "breadcrumb", "caption", "social", "comment"))
            self.stack.append((tag, blocked or (self.stack[-1][1] if self.stack else False), classes))
            in_article = any(t in {"article", "main"} or any(x in cls for x in ("article", "story", "content")) for t, _blocked, cls in self.stack)
            if tag == "h1" and not self.stack[-1][1] and in_article:
                self.in_h1, self.h1_parts = True, []
            if tag == "title":
                self.in_title = True
            in_article = any(t in {"article", "main"} or any(x in cls for x in ("article", "story", "content")) for t, _blocked, cls in self.stack)
            if tag == "p" and not self.stack[-1][1] and in_article:
                self.current = {"classes": classes, "text": []}

        def handle_endtag(self, tag):
            tag = tag.lower()
            if tag == "script" and self.in_script:
                self.jsonld.append("".join(self.script_data)); self.in_script = False
            if tag == "h1":
                self.in_h1 = False
            if tag == "title":
                self.in_title = False
            if tag == "p" and self.current is not None:
                text = " ".join(" ".join(self.current["text"]).split())
                if len(text) >= 30:
                    self.blocks.append((text, self.current["classes"]))
                self.current = None
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    self.stack = self.stack[:i]
                    break

        def handle_data(self, data):
            if self.in_script: self.script_data.append(data)
            if self.in_h1: self.h1_parts.append(data.strip())
            if self.in_title: self.title_parts.append(data.strip())
            if self.current is not None and not (self.stack and self.stack[-1][1]):
                self.current["text"].append(data.strip())

    parser = ArticleParser()
    parser.feed((html or "")[:2_000_000])
    nodes = []
    def visit(value):
        if isinstance(value, dict):
            typ = value.get("@type", [])
            if isinstance(typ, str): typ = [typ]
            if any(str(t).lower() in {"article", "newsarticle", "reportagenewsarticle", "blogposting"} for t in typ):
                nodes.append(value)
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    for block in parser.jsonld:
        try: visit(json.loads(block))
        except (json.JSONDecodeError, RecursionError): pass
    headline = next((str(n.get("headline") or n.get("name", "")).strip() for n in nodes if n.get("headline") or n.get("name")), "")
    title = headline
    title_source = "json-ld:headline" if headline else ""
    if not title:
        title = " ".join(parser.h1_parts).strip()
        title_source = "html:h1" if title else ""
    if not title:
        title = parser.meta.get("og:title", "").strip()
        title_source = "meta:og:title" if title else ""
    description = next((str(n.get("description", "")).strip() for n in nodes if n.get("description")), "")
    abstract = description or parser.meta.get("article:description", "").strip() or parser.meta.get("og:description", "").strip() or parser.meta.get("description", "").strip()
    abstract_source = ("json-ld:description" if description else "meta:article:description" if parser.meta.get("article:description") else "meta:og:description" if parser.meta.get("og:description") else "meta:description" if parser.meta.get("description") else "")
    lead_candidates = [text for text, classes in parser.blocks if any(x in classes for x in ("sapo", "summary", "lead", "description", "article-intro"))]
    if lead_candidates:
        lead, lead_source = _truncate_word_boundary(lead_candidates[0], 2000), "html:article-sapo"
    else:
        paragraphs = [text for text, _ in parser.blocks[:3]]
        lead, lead_source = _truncate_word_boundary(" ".join(paragraphs), 2000), ("html:article-paragraphs" if paragraphs else "")
        if not lead:
            extracted = trafilatura.extract(html, include_comments=False, include_tables=False, output_format="txt") or ""
            lead = _truncate_word_boundary(" ".join(extracted.splitlines()[:3]), 2000)
            lead_source = "trafilatura:lead" if lead else ""
    if not abstract and lead_candidates:
        abstract, abstract_source = lead_candidates[0][:2000], "html:article-sapo"
    author = next((str(n.get("author", {}).get("name", "")).strip() if isinstance(n.get("author"), dict) else ", ".join(str(a.get("name", "")) for a in n.get("author", []) if isinstance(a, dict)) for n in nodes if n.get("author")), "")
    author = author or parser.meta.get("author", "").strip() or parser.meta.get("article:author", "").strip()
    return title, title_source, abstract, abstract_source, lead, lead_source, author


def _truncate_word_boundary(text, limit=2000):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut.rsplit(" ", 1)[0].rstrip(" ,;:-")


def _extract_article_html(url, html, entity_ids, matcher=None, matcher_by_id=None):
    if not _is_article_url(url):
        raise ValueError("URL cuối không thuộc dạng trang bài báo")
    title, title_source, abstract, abstract_source, article_lead, lead_source, author = _extract_article_fields(html)
    page_title, _, _ = _html_metadata(html)
    challenge_title = re.search(r"\b(log ?in|sign ?in|captcha|consent|access denied|verify)\b", page_title, re.I)
    challenge_body = re.search(r"(unusual traffic|verify you are human|checking your browser|before you continue)", re.sub(r"<[^>]+>", " ", (html or "")[:100_000]), re.I)
    if challenge_title or (challenge_body and not article_lead):
        raise ValueError("trang đăng nhập/consent/CAPTCHA; chưa xác minh được bài báo")
    raw, date_source, published, conflict = _page_publication_dates(html)
    if not abstract:
        abstract_source = ""
    if not title and not article_lead:
        raise ValueError("thiếu tiêu đề và đoạn mở đầu trên trang bài báo")
    if matcher_by_id is not None and entity_ids:
        candidate_terms = [term for entity_id in entity_ids for term in matcher_by_id.get(entity_id, ())]
    elif matcher is not None:
        candidate_terms = matcher
    else:
        entities = _entities()
        candidate_terms = _relevance_terms([e for e in entities if not entity_ids or e["entity_id"] in entity_ids])
    matches = _relevance_matches(title, title + "\n" + abstract + "\n" + article_lead, candidate_terms)
    relevance = "liên quan" if matches else "cần duyệt liên quan"
    return {"url": url, "html": html, "title": title, "title_source": title_source,
            "author": author, "raw": raw, "date_source": date_source, "published": published,
            "published_iso": _published_iso(raw), "conflict": conflict, "article_lead": article_lead,
            "lead_source": lead_source, "abstract": abstract, "abstract_source": abstract_source,
            "content": article_lead or abstract, "relevance": relevance, "matched": matches}


def _extract_page(url, entity_ids, matcher=None, matcher_by_id=None):
    response = _polite_get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    result = _extract_article_html(response.url, response.text, entity_ids, matcher, matcher_by_id)
    result.update(http_status=response.status_code, response=response)
    return result


class _BrowserBroker:
    """One reusable Chromium instance; each task owns and closes its page."""
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.ready = asyncio.run_coroutine_threadsafe(self._start(), self.loop).result(timeout=40)

    async def _start(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.semaphore = asyncio.Semaphore(2)

    async def _resolve(self, url):
        async with self.semaphore:
            page = await self.browser.new_page()
            try:
                deadline = time.monotonic() + 30
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                stable_url = ""
                stable_since = 0.0
                while time.monotonic() < deadline:
                    current_url = page.url
                    host = (urllib.parse.urlparse(current_url).hostname or "").lower()
                    is_publisher = host and host != "news.google.com" and not host.endswith(".google.com")
                    if is_publisher:
                        if current_url != stable_url:
                            stable_url, stable_since = current_url, time.monotonic()
                        elif time.monotonic() - stable_since >= 1.0:
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=max(1, min(1500, int((deadline - time.monotonic()) * 1000))))
                            except Exception:
                                pass
                            break
                    else:
                        stable_url, stable_since = "", 0.0
                    await page.wait_for_timeout(250)
                final = page.url
                if not stable_url or final != stable_url:
                    raise ValueError(f"redirect chưa ổn định sau 30 giây; URL cuối quan sát được: {final}")
                try:
                    html = await page.content()
                except Exception:
                    # A publisher can start one more client-side navigation just as
                    # the redirect settles. Wait briefly and read the settled DOM.
                    remaining_ms = max(1, min(1500, int((deadline - time.monotonic()) * 1000)))
                    await page.wait_for_load_state("domcontentloaded", timeout=remaining_ms)
                    await page.wait_for_timeout(min(300, remaining_ms))
                    final = page.url
                    html = await page.content()
                title = (await page.title()).casefold()
                body = (await page.locator("body").inner_text(timeout=2000)).casefold()[:4000]
                challenge_title = any(x in title for x in ("captcha", "sign in", "log in", "consent", "access denied"))
                challenge_body = any(x in body for x in ("unusual traffic", "verify you are human", "checking your browser", "before you continue"))
                challenge = challenge_title or challenge_body
                if challenge or not _is_article_url(final):
                    raise ValueError("trang trung gian/consent/đăng nhập/CAPTCHA; chưa tới trang bài báo")
                return final, html
            finally:
                await page.close()

    def resolve(self, url):
        return asyncio.run_coroutine_threadsafe(self._resolve(url), self.loop).result(timeout=35)

    async def _stop(self):
        await self.browser.close()
        await self.playwright.stop()

    def close(self):
        try:
            asyncio.run_coroutine_threadsafe(self._stop(), self.loop).result(timeout=10)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)


def _fetch_crawl_item(original, previously_resolved, subjects, source_name, source_kind, allow_resolve, rss_abstract, matcher, matcher_by_id, sources, browser=None):
    ids = [x for x in re.split(r"[,|]", subjects) if x]
    host = ""
    url = previously_resolved or original
    resolved_new = False
    step = "resolve_http"
    status_code, response_url, snippet = None, "", ""
    browser_html = ""
    try:
        parsed = urllib.parse.urlparse(original)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            raise ValueError("URL không phải HTTP/HTTPS hợp lệ")
        if host == "news.google.com" and not previously_resolved:
            if not allow_resolve:
                return {"kind": "pending", "original": original}
            try:
                url, intermediate = _google_news_response(original)
                status_code, response_url = getattr(intermediate, "status_code", None), getattr(intermediate, "url", "")
                snippet = _response_snippet(intermediate, 800)
            except Exception as exc:
                url = ""
                http_resolve_error = str(exc)
            if not url and browser:
                step = "resolve_browser"
                url, browser_html = browser.resolve(original)
            elif not url:
                raise ValueError(http_resolve_error if 'http_resolve_error' in locals() else "Google News trả trang trung gian; bật --browser-fallback để thử Chromium")
            resolved_new = True
        if not _is_article_url(url):
            raise ValueError("URL đích chưa được xác minh là trang bài báo")
        step = "fetch_article"
        try:
            extracted = _extract_page(url, ids, matcher, matcher_by_id)
            status_code = extracted["http_status"]
            response_url = extracted["response"].url
        except Exception as exc:
            if not browser_html:
                raise
            extracted = _extract_article_html(url, browser_html, ids, matcher, matcher_by_id)
            status_code = status_code or 200
            response_url = url
            extracted["http_status"] = status_code
            extracted["response"] = None
        if browser and (not extracted["title"] or not extracted["published"] or not extracted["article_lead"]):
            step = "extract_metadata" if not extracted["title"] or not extracted["published"] else "extract_lead"
            try:
                rendered_url, rendered_html = browser.resolve(url)
                rendered = _extract_article_html(rendered_url, rendered_html, ids, matcher, matcher_by_id)
                if not extracted["title"]: extracted["title"], extracted["title_source"] = rendered["title"], rendered["title_source"]
                if not extracted["abstract"]: extracted["abstract"], extracted["abstract_source"] = rendered["abstract"], rendered["abstract_source"]
                if not extracted["published"]: extracted["raw"], extracted["date_source"], extracted["published"], extracted["published_iso"] = rendered["raw"], rendered["date_source"], rendered["published"], rendered["published_iso"]
                if not extracted["article_lead"]: extracted["article_lead"], extracted["lead_source"] = rendered["article_lead"], rendered["lead_source"]
                if not extracted["author"]: extracted["author"] = rendered["author"]
                if not extracted.get("html"): extracted["html"] = rendered_html
            except Exception:
                pass
        missing = [name for name, value in (("title", extracted["title"]), ("published_at", extracted["published"]), ("article_lead", extracted["article_lead"])) if not value]
        incomplete_step = "extract_metadata" if any(x in missing for x in ("title", "published_at")) else ("extract_lead" if missing else "complete")
        extracted.update(kind="article", original=original, resolved_url=url, final=extracted["url"], ids=ids,
                         source=_source_for_url(extracted["url"], sources), source_name=source_name,
                         source_kind=source_kind, rss_abstract=rss_abstract, resolved_new=resolved_new, missing_fields=missing,
                         http_status=status_code, response_snippet=snippet,
                         step=incomplete_step)
        return extracted
    except Exception as exc:
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status_code = exc.response.status_code
            response_url = exc.response.url
            snippet = _response_snippet(exc.response, 800)
        return {"kind": "error", "original": original, "error": str(exc), "step": step,
                "http_status": status_code, "final_url": response_url, "response_snippet": snippet,
                "resolved_url": url if url and url != original and _is_article_url(url) else "",
                "resolved_new": resolved_new, "resolution_state": "error" if host == "news.google.com" else "pending"}


def _filter_queue_rows(rows, entity_ids=None, limit=None):
    """Filter exact entity IDs first, then apply the requested batch limit."""
    selected_entities = set(entity_ids or [])
    if selected_entities:
        rows = [row for row in rows if selected_entities.intersection(x for x in re.split(r"[,|]", row[2] or "") if x)]
    eligible = len(rows)
    if limit is None:
        return rows, eligible, 0
    selected = rows[:max(0, limit)]
    return selected, eligible, eligible - len(selected)


def crawl(limit=None, entity_ids=None, resolve_limit=50, workers=8, browser_fallback=False):
    db = _db()
    accepted = review = out_period = errors = downloaded = resolved = complete_fields = 0
    error_counts, error_samples = {}, []
    error_steps, missing_field_counts = {}, {}
    browser = None
    try:
        rows = db.execute("SELECT url,resolved_url,subject_ids,source_name,source_kind,attempts,rss_abstract FROM urls WHERE state IN ('discovered','error') ORDER BY CASE WHEN attempts=0 THEN 0 ELSE 1 END,discovered_at").fetchall()
        selected_entities = set(entity_ids or [])
        rows, eligible_count, deferred_limit = _filter_queue_rows(rows, entity_ids, limit)
        tasks, deferred = [], 0
        resolve_budget = max(0, resolve_limit)
        for original, previously_resolved, subjects, source_name, source_kind, attempts, rss_abstract in rows:
            tasks.append((original, previously_resolved, subjects, source_name, source_kind, rss_abstract))
        selected = tasks
        # Apply resolve budget after limit so a small crawl does not reserve resolution slots for deferred URLs.
        resolve_budget = max(0, resolve_limit)
        selected_tasks = []
        for task in selected:
            try: is_google = (urllib.parse.urlparse(task[0]).hostname or "").lower() == "news.google.com" and not task[1]
            except ValueError: is_google = False
            allow = not is_google or resolve_budget > 0
            if is_google and allow: resolve_budget -= 1
            elif is_google: deferred += 1
            selected_tasks.append((*task[:5], allow, task[5]))
        if browser_fallback and selected_tasks:
            try: browser = _BrowserBroker()
            except Exception as exc:
                raise RuntimeError(f"Không khởi tạo được Chromium; cài bằng `uv run playwright install chromium`: {exc}") from exc
        all_entities = _entities()
        entities = [e for e in all_entities if not selected_entities or e["entity_id"] in selected_entities]
        all_match_terms = _relevance_terms(all_entities)
        matcher = [term for term in all_match_terms if not selected_entities or term[0] in selected_entities]
        matcher_by_id = {}
        for term in matcher: matcher_by_id.setdefault(term[0], []).append(term)
        sources = _sources()
        content_owner = {r.get("content_hash"): r.get("document_id") for r in _read_docs() if r.get("content_hash") and r.get("document_id")}
        processed = 0
        print(f"Bắt đầu crawl {len(selected_tasks)} URL trong {eligible_count} phù hợp; hoãn do --limit={deferred_limit}, hoãn do --resolve-limit={max(0, deferred)}; workers={max(1, workers)}; browser fallback={'bật' if browser_fallback else 'tắt'}.", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(_fetch_crawl_item, *task[:5], task[5], task[6], matcher, matcher_by_id, sources, browser) for task in selected_tasks]
            records = []
            for future in as_completed(futures):
                result = future.result(); processed += 1; original = result["original"]
                if result["kind"] == "pending":
                    db.execute("UPDATE urls SET resolution_state='pending',error='đợi lượt giải URL Google News',updated_at=?,attempts=attempts+1 WHERE url=?", (now_iso(), original))
                elif result["kind"] == "error":
                    errors += 1
                    message = result["error"]
                    error_counts[message] = error_counts.get(message, 0) + 1
                    error_steps[result["step"]] = error_steps.get(result["step"], 0) + 1
                    error_samples.append({"url": original, **{k: result.get(k) for k in ("error", "step", "http_status", "final_url", "response_snippet")}})
                    db.execute("UPDATE urls SET state='error',resolved_url=CASE WHEN ?='' THEN resolved_url ELSE ? END,final_url=?,updated_at=?,error=?,exclusion_reason=?,resolution_state=?,attempts=attempts+1 WHERE url=?", (result.get("resolved_url", ""), result.get("resolved_url", ""), result.get("final_url", ""), now_iso(), result["error"], result["step"], result["resolution_state"], original))
                else:
                    resolved += bool(result.get("resolved_new")); downloaded += 1
                    missing = result["missing_fields"]
                    if not missing: complete_fields += 1
                    for field in missing: missing_field_counts[field] = missing_field_counts.get(field, 0) + 1
                    published = result["published"]
                    d = date.fromisoformat(published) if published else None
                    if d and not (PERIOD_START <= d <= PERIOD_END): state, status = "out_of_period", "loại bỏ"; out_period += 1
                    elif missing or result["conflict"] or result["relevance"] != "liên quan": state, status = "needs_review", "cần kiểm tra"; review += 1
                    else: state, status = "crawled", "hợp lệ"; accepted += 1
                    html = result.get("html", "")
                    raw_path = ""
                    if html:
                        html_path = WEB_DIR / "html" / (hashlib.sha256(original.encode()).hexdigest() + ".html")
                        html_path.parent.mkdir(parents=True, exist_ok=True); html_path.write_text(html, encoding="utf-8"); raw_path = str(html_path.relative_to(ROOT))
                    docid = "DOC_WEB_" + hashlib.sha256(original.encode()).hexdigest()[:20]
                    content = result["content"]
                    content_hash = hashlib.sha256(content.encode()).hexdigest() if content else ""
                    duplicate_of = content_owner.get(content_hash, "") if content_hash else ""
                    if duplicate_of == docid: duplicate_of = ""
                    if content_hash: content_owner.setdefault(content_hash, docid)
                    reason = "; ".join([*(f"thiếu {x}" for x in missing), result["conflict"], *( ["ngoài kỳ"] if state == "out_of_period" else [] )]).strip("; ")
                    if result["relevance"] != "liên quan": reason = "; ".join(filter(None, (reason, "chưa khớp tên thực thể trong tiêu đề/nội dung")))
                    records.append({"document_id": docid, "url": original, "resolved_url": result["resolved_url"], "final_url": result["final"], "source_name": result["source"].get("source_name") or result["source_name"], "source_type": result["source"].get("source_type", "website chưa xác minh"), "title": result["title"], "title_source": result["title_source"], "abstract": result["abstract"], "abstract_source": result["abstract_source"], "rss_abstract": result["rss_abstract"], "article_lead": result["article_lead"], "lead_source": result["lead_source"], "published_at": published, "published_at_iso": result["published_iso"], "published_at_raw": result["raw"], "published_at_source": result["date_source"], "published_at_conflict": result["conflict"], "collected_at": now_iso(), "content": content, "raw_html_path": raw_path, "collection_method": result["source_kind"] or "web", "document_status": status, "author": result["author"], "content_hash": content_hash, "duplicate_content_of": duplicate_of, "crawl_relevance_status": result["relevance"], "review_reason": reason, "query_entity_ids": ",".join(result["ids"]), "seed_ids": ",".join(sorted(set(result["matched"])))})
                    db.execute("UPDATE urls SET state=?,resolved_url=?,final_url=?,updated_at=?,error='',resolution_state='resolved',exclusion_reason=? WHERE url=?", (state, result["resolved_url"], result["final"], now_iso(), reason, original))
                if processed % 10 == 0 or processed == len(selected_tasks):
                    print(f"Tiến độ crawl: {processed}/{len(selected_tasks)}; trang bài báo {downloaded}, đủ trường {accepted}, thiếu trường/chờ duyệt {review}, giải được URL {resolved}, lỗi {errors}.", flush=True)
                if processed % max(1, workers * 4) == 0 or processed == len(selected_tasks):
                    if records: _save_docs(records); records.clear()
                    db.commit()
        report = {"selected": len(selected_tasks), "eligible_before_limit": eligible_count, "deferred_by_limit": deferred_limit, "deferred_by_resolve_limit": deferred, "processed_this_run": processed, "publisher_pages_fetched": downloaded, "complete_fields": complete_fields, "accepted_for_analysis": accepted, "missing_fields_or_review": review, "missing_field_counts": missing_field_counts, "out_of_period": out_period, "resolved_links": resolved, "errors": errors, "error_steps": error_steps, "error_counts": error_counts, "error_samples": error_samples[:100], "workers": max(1, workers), "browser_fallback": browser_fallback}
        INTERIM_DIR.mkdir(parents=True, exist_ok=True)
        (INTERIM_DIR / "web_crawl_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Tải xong: {downloaded} trang bài báo; đủ trường {accepted}, thiếu trường/chờ duyệt {review}, ngoài kỳ {out_period}, lỗi {errors}.")
    finally:
        if browser: browser.close()
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
