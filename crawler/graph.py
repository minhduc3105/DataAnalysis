import csv
import difflib
import re
import unicodedata
from collections import Counter, defaultdict
from itertools import combinations

from .common import normalize_name, now_iso, read_seeds, today_iso
from .config import INTERIM_DIR, SEEDS_PATH
from .extract import DOCUMENTS_PATH, MENTIONS_PATH
from .layer1_extract import _org_key
from .layer2 import _canonical, load_aliases
from .scope import VI_CHARS
from .shows import read_shows

GRAPH_DIR = INTERIM_DIR / "graph"
ID_REGISTRY = GRAPH_DIR / "id_registry.csv"
WEB_GRAPH_DIR = INTERIM_DIR.parent / "processed" / "web" / "graph_clean"
UNDIRECTED = {"COLLABORATED_WITH", "DISPUTED_WITH"}
PREFIX = {"Person": "PER", "Song": "SON", "Album": "ALB", "Company": "COM", "Show": "SHO", "Event": "EVT", "Group": "GRO", "Brand": "BRA", "Relation": "REL", "Evidence": "EVD"}
VERIFIED, PENDING, UNVERIFIED = "đã xác minh", "chờ kiểm tra", "chưa xác minh"

ENTITY_COLUMNS = [
    "entity_id", "entity_type", "canonical_name", "aliases", "verification_status", "created_at", "notes", "release_year", "season_or_year", "official_url",
    "seed_id", "n_documents", "n_relations",
]
RELATION_COLUMNS = [
    "relation_id", "source_entity_id", "relation_type", "target_entity_id", "verification_status", "is_derived", "valid_from", "valid_to", "role_detail", "notes",
    "source_name", "target_name", "n_documents",
]
EVIDENCE_COLUMNS = [
    "evidence_id", "relation_id", "document_id", "quote", "sentence_location", "extraction_method", "review_status", "review_note", "confidence_score", "url",
]

COMPANY_ALIASES_PATH = SEEDS_PATH.with_name("company_aliases.csv")
NOT_LABEL = re.compile(r"network|channel|\bmcn\b", re.IGNORECASE)
# Chỉ show thi đấu mới có thí sinh; show/concert còn lại ghi là biểu diễn tại chương trình.
COMPETITION = re.compile(r"say hi|vượt ngàn chông gai|tân binh|rap việt|masked singer|ca sĩ mặt nạ|king of rap|idol|chị đẹp", re.IGNORECASE)
RELEASE_ROLES = {"label", "audio_distributor", "rights_owner"}
ORGANIZER_ROLES = {"format_owner", "rights_owner", "broadcaster", "format_distributor"}
CREW_PREFIX = {"hustlang", "rpt"}
CONFIDENCE = {"quy tắc: tên kèm nhóm trong ngoặc": 0.85,"quy tắc: tiêu đề": 0.8, "quy tắc: dòng credit": 0.9, "quy tắc: dòng bản quyền/label": 0.8, "quy tắc: brand": 0.6}


class Registry:
    """Giữ ID cố định giữa các lần chạy để bảng duyệt tay không bị lệch."""

    def __init__(self):
        self.ids: dict[tuple[str, str], str] = {}
        self.next: Counter = Counter()
        if ID_REGISTRY.exists():
            with ID_REGISTRY.open(encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    self.ids[(r["kind"], r["key"])] = r["id"]
                    prefix, num = r["id"].rsplit("_", 1)
                    self.next[prefix] = max(self.next[prefix], int(num))

    def get(self, kind: str, key: str) -> str:
        if (kind, key) not in self.ids:
            prefix = PREFIX[kind]
            self.next[prefix] += 1
            width = 6 if kind in {"Relation", "Evidence"} else 4
            self.ids[(kind, key)] = f"{prefix}_{self.next[prefix]:0{width}d}"
        return self.ids[(kind, key)]

    def save(self) -> None:
        GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        with ID_REGISTRY.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["kind", "key", "id"])
            w.writerows([k, key, i] for (k, key), i in sorted(self.ids.items(), key=lambda x: x[1]))


def _raw_company_key(name: str) -> str:
    return re.sub(r"(llc|pteltd|pte|inc|limitedliabilitycompany)$", "", _org_key(name))


COMPANY_DISPLAY: dict[str, str] = {}


def _load_company_aliases() -> dict[str, str]:
    if not COMPANY_ALIASES_PATH.exists():
        return {}
    with COMPANY_ALIASES_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    COMPANY_DISPLAY.update({_raw_company_key(r["canonical_name"]): r["canonical_name"] for r in rows})
    return {_raw_company_key(r["alias"]): _raw_company_key(r["canonical_name"]) for r in rows}


COMPANY_ALIASES = _load_company_aliases()
GROUP_WORDS = re.compile(r"\b(?:band|choir|crew|ban nhạc|hợp xướng|boys|girls|brothers|squad|gang|collective)\b", re.IGNORECASE)


BLOCKLIST_PATH = SEEDS_PATH.with_name("entity_blocklist.csv")


def load_blocklist() -> set[tuple[str, str]]:
    """Tên người dùng đánh dấu sai trong seeds/entity_blocklist.csv; chạy lại graph sẽ không tạo lại node đó."""
    if not BLOCKLIST_PATH.exists():
        return set()
    with BLOCKLIST_PATH.open(encoding="utf-8-sig", newline="") as f:
        return {(r["entity_type"].strip(), normalize_name(r["name"])) for r in csv.DictReader(f) if r.get("name")}


OVERRIDES_PATH = SEEDS_PATH.with_name("entity_overrides.csv")
VARIANT_TAIL = re.compile(r"\s+(?:\d{4}|\d0s|drill|house|rnb|r&b|vmix|rework|freestyle|review|all|uni5)$", re.IGNORECASE)
PROD_PREFIX = re.compile(r"^prod\.?\s*(?:by\s*)?(?=\S)", re.IGNORECASE)


def load_overrides() -> dict[str, tuple[str, str]]:
    """seeds/entity_overrides.csv: tên rút từ tiêu đề/credit thực ra là Brand, Company, Group hoặc rác (drop)."""
    if not OVERRIDES_PATH.exists():
        return {}
    with OVERRIDES_PATH.open(encoding="utf-8-sig", newline="") as f:
        return {normalize_name(r["name"]): (r["entity_type"].strip(), (r.get("canonical_name") or r["name"]).strip()) for r in csv.DictReader(f) if r.get("name")}


VI_SURNAMES = set(
    "nguyen tran le pham hoang huynh phan vu vo dang bui do ho ngo duong ly dinh truong lam mai cao ha luu trinh doan thai chu ta kieu quach lu tong "
    "vuong ton la giang khuc kim au luong tieu chau van quan dam phung nghiem mac han thach trieu lai ung banh an bach diep khong mach son tang to tu "
    "hua ninh lieu nong dao hong cu giap ong phuong tat tiet thieu lang trang hau bao".split()
)


VI_SURNAMES_ACCENTED = set(
    "nguyễn trần lê phạm hoàng huỳnh phan vũ võ đặng bùi đỗ hồ ngô dương lý đinh trương lâm mai cao hà lưu trịnh đoàn thái chu tạ kiều quách lữ "
    "tống vương tôn la giang khúc kim âu lương tiêu châu văn quan đàm phùng nghiêm mạc hàn thạch triệu lại ứng bành an bạch diệp khổng mạch sơn "
    "tăng tô từ hứa ninh liêu nông đào hồng cù giáp ông phương tất tiết thiều lăng trang hầu bảo quyền uông lò lục lã doãn khương phó viên đồng "
    "đậu mã thân quang trình lạc ôn nhan vi liên phí trác thủy khúc hàng".split()
)
SHOW_ROLES_PATH = SEEDS_PATH.with_name("show_roles.csv")


def load_show_roles() -> set[tuple[str, str]]:
    """(khóa người, khóa tên show) của HLV/giám khảo; chỉ dùng để không ghi họ là thí sinh, không tạo cạnh vì không có tài liệu."""
    if not SHOW_ROLES_PATH.exists():
        return set()
    aliases = load_aliases()
    with SHOW_ROLES_PATH.open(encoding="utf-8-sig", newline="") as f:
        return {(_canonical(r["person"], aliases), normalize_name(r["show_name"])) for r in csv.DictReader(f) if r.get("person")}


def _one_typo(a: str, b: str) -> bool:
    """Đúng 1 lần thêm/bớt 1 ký tự hoặc đảo 2 ký tự liền nhau; thay 1 chữ thì không (Tùng ≠ Hùng là hai người)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


TONE_MARKS = {"̀", "́", "̃", "̉", "̣"}


def _vowel_key(text: str) -> str:
    """Bỏ dấu thanh nhưng giữ biến âm (ư ơ ă â ê ô đ): "Thuỳ"="Thùy", "Hùng"≠"Hưng"."""
    stripped = "".join(c for c in unicodedata.normalize("NFD", text) if c not in TONE_MARKS)
    return " ".join(re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", stripped).casefold()).split())


def _has_accent(text: str) -> bool:
    return any(unicodedata.category(c) == "Mn" for c in unicodedata.normalize("NFD", text)) or "đ" in text.lower()


def _company_key(name: str) -> str:
    key = _raw_company_key(name)
    return COMPANY_ALIASES.get(key, key)


def song_key(name: str) -> str:
    """Tên ngắn giữ dấu (Đợi ≠ Đôi ≠ Đời); tên dài bỏ dấu để gộp cách viết không dấu."""
    plain = normalize_name(name)
    if len(plain.split()) > 3:
        return plain
    return " ".join(re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", name).casefold()).split())


def _display(variants: Counter) -> str:
    """Ưu tiên cách viết không viết hoa toàn bộ, có dấu, rồi gặp nhiều nhất."""
    def accents(s: str) -> int:
        return sum(1 for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) == "Mn")

    ranked = sorted(variants.items(), key=lambda x: (x[0].isupper(), accents(x[0]) == 0, -x[1], -accents(x[0]), x[0]))
    return ranked[0][0]


class Graph:
    def __init__(self):
        self.reg = Registry()
        self.entities: dict[str, dict] = {}
        self.keys: dict[str, str] = {}
        self.blocked: set[tuple[str, str]] = set()
        self.fixed_name: dict[str, str] = {}
        self.names: dict[str, Counter] = defaultdict(Counter)
        self.docs_of: dict[str, set] = defaultdict(set)
        self.relations: dict[tuple, dict] = {}
        self.evidence: dict[tuple, dict] = {}

    def entity(self, etype: str, key: str, name: str, doc_id: str = "", **fields) -> str | None:
        # Tên seed rất ngắn (V#) vẫn giữ; tên rút tự động dưới 2 ký tự thường là rác.
        if not key or (len(key) < 2 and not fields.get("seed_id")):
            return None
        if not fields.get("seed_id") and (etype, normalize_name(name)) in self.blocked:
            return None
        eid = self.reg.get(etype, key)
        self.keys[eid] = key
        if eid not in self.entities:
            self.entities[eid] = {
                "entity_id": eid, "entity_type": etype, "verification_status": UNVERIFIED, "created_at": today_iso(), "notes": "", "release_year": "",
                "season_or_year": "", "official_url": "", "seed_id": "",
            }
        e = self.entities[eid]
        for k, v in fields.items():
            if v and not e.get(k):
                e[k] = v
        self.names[eid][name.strip()] += 1
        if doc_id:
            self.docs_of[eid].add(doc_id)
        return eid

    def relate(self, src, rtype, tgt, doc, mention, role_detail="", derived=False):
        if not src or not tgt or src == tgt:
            return
        if rtype == "COLLABORATED_WITH":
            src, tgt = sorted((src, tgt))
        key = (src, rtype, tgt)
        if key not in self.relations:
            self.relations[key] = {
                "relation_id": self.reg.get("Relation", "|".join(key)), "source_entity_id": src, "relation_type": rtype, "target_entity_id": tgt,
                "verification_status": PENDING, "is_derived": "có" if derived else "không", "valid_from": "", "valid_to": "", "role_detail": set(), "notes": "",
                "docs": set(),
            }
        rel = self.relations[key]
        if role_detail:
            rel["role_detail"].add(role_detail)
        rel["docs"].add(doc["document_id"])
        ev_key = (rel["relation_id"], doc["document_id"], mention["location"])
        if ev_key not in self.evidence:
            method = "suy ra từ quan hệ PERFORMED/FEATURED_ON cùng bài" if derived else mention["method"]
            self.evidence[ev_key] = {
                "evidence_id": self.reg.get("Evidence", "|".join(ev_key)), "relation_id": rel["relation_id"], "document_id": doc["document_id"],
                "quote": mention["quote"], "sentence_location": mention["location"], "extraction_method": method, "review_status": PENDING,
                "review_note": "", "confidence_score": 0.6 if derived else CONFIDENCE.get(mention["method"], 0.7), "url": doc["url"],
            }


def build() -> None:
    aliases = load_aliases()
    seeds = read_seeds()
    shows = {s["show_id"]: s for s in read_shows()}
    with DOCUMENTS_PATH.open(encoding="utf-8-sig", newline="") as f:
        docs = {d["document_id"]: d for d in csv.DictReader(f)}
    with MENTIONS_PATH.open(encoding="utf-8-sig", newline="") as f:
        mentions = list(csv.DictReader(f))

    g = Graph()
    person_index: dict[str, str] = {}
    seed_entity: dict[str, str] = {}
    seed_keys: dict[str, set[str]] = {}
    seed_spelling: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for s in seeds:
        etype = "Group" if s["entity_type"] == "Group" else "Person"
        key = _canonical(s["name"], aliases)
        url = f"https://www.youtube.com/channel/{s['youtube_channel_id']}" if s.get("youtube_channel_id") else ""
        status = VERIFIED if s.get("verification_status") == "đã duyệt" else PENDING
        eid = g.entity(etype, key, s["name"], seed_id=s["seed_id"], official_url=url, notes=s.get("genre_group", ""))
        g.fixed_name[eid] = s["name"]
        g.entities[eid]["verification_status"] = status
        seed_entity[s["seed_id"]] = eid
        seed_keys[s["seed_id"]] = {_canonical(n, aliases) for n in [s["name"], *s.get("aliases", "").split(" | ")] if normalize_name(n)}
        for n in [s["name"], *s.get("aliases", "").split(" | "), s.get("youtube_channel_name", "")]:
            if _has_accent(n):
                seed_spelling[eid].setdefault(normalize_name(n), set()).add(_vowel_key(n))
        for n in [s["name"], *s.get("aliases", "").split(" | "), s.get("youtube_channel_name", "")]:
            if normalize_name(n):
                person_index.setdefault(_canonical(n, aliases), eid)
    show_entity: dict[str, str] = {}
    for sid, s in shows.items():
        label = f"{s['show_name']} mùa {s['season']}" if s.get("season") else f"{s['show_name']} {s.get('year', '')}".strip()
        eid = g.entity(
            s["entity_type"], sid, label, season_or_year=s.get("season") or s.get("year", ""), official_url=(s.get("playlist_urls") or "").split(" ")[0],
            notes=f"năm {s.get('year', '')}; kênh {s.get('channel_name', '')}",
        )
        g.entities[eid]["verification_status"] = VERIFIED
        show_entity[sid] = eid

    song_keys = {normalize_name(m["mention"]) for m in mentions if m["mention_type"] == "Song"}
    nospace_index = {k.replace(" ", ""): k for k in person_index}
    # Tên gốc của alias cũng tra được khi viết liền ("QuangAnhRhyder" → RHYDER).
    for s in seeds:
        for n in [s["name"], *s.get("aliases", "").split(" | ")]:
            if normalize_name(n):
                nospace_index.setdefault(normalize_name(n).replace(" ", ""), _canonical(n, aliases))
    seed_nospace = {k: v for k, v in nospace_index.items() if len(k) >= 6}
    g.blocked = load_blocklist()
    overrides = load_overrides()

    def person(name: str, doc_id: str, doc_seed_keys: dict[str, str], from_title: bool = True) -> str | None:
        name = VARIANT_TAIL.sub("", PROD_PREFIX.sub("", name.strip())).strip() or name
        override = overrides.get(normalize_name(name))
        if override:
            etype, canonical = override
            # Brand chỉ tin khi đứng trong tiêu đề ("X x CLOSEUP"); trong dòng credit "HENNESSY" là nghệ danh rapper.
            if etype == "drop" or (etype == "Brand" and not from_title):
                return None
            if etype != "Person":
                key = {"Company": _company_key, "Brand": _org_key}.get(etype, normalize_name)(canonical)
                return g.entity(etype, key, canonical, doc_id)
        key = _canonical(name, aliases)
        # Mảnh tên seed trong video của chính seed đó ("Jack" trong Jack - J97, "Cá" trong Cá Hồi Hoang).
        if key not in person_index:
            key = next((k for k in doc_seed_keys if f" {key} " in f" {k} "), key)
        # "Justa Tee" = "JustaTee", "QUEEN B" = "QUEENB".
        key = nospace_index.get(key.replace(" ", ""), key)
        # Lỗi gõ đúng 1 ký tự hoặc đảo 2 ký tự so với seed (RYHMASTIC → Rhymastic); lệch hơn thì là người khác (Hoàng Yến ≠ Hoàng Duyên).
        flat = key.replace(" ", "")
        # Tên ngắn lệch 1 chữ thường là hai người khác nhau (Duy Khang ≠ Duy Khánh), nên chỉ so gần đúng với tên ≥ 9 ký tự.
        if key not in person_index and len(flat) >= 9:
            close = [k for k in difflib.get_close_matches(flat, seed_nospace, n=3, cutoff=0.8) if _one_typo(flat, k)]
            if len(close) == 1:
                key = seed_nospace[close[0]]
        # Cùng chữ khi bỏ dấu nhưng khác biến âm là hai người: "Tuấn Hùng" ≠ seed "Tuấn Hưng".
        spellings = seed_spelling.get(person_index.get(key, ""), {}).get(normalize_name(name))
        if spellings and _has_accent(name) and _vowel_key(name) not in spellings:
            key = f"{key}|{_vowel_key(name)}"
        if key in person_index:
            eid = person_index[key]
            g.names[eid][name.strip()] += 1
            g.docs_of[eid].add(doc_id)
            return eid
        if key in song_keys:
            return None
        eid = g.entity("Group" if GROUP_WORDS.search(name) else "Person", key, name, doc_id)
        if eid:
            person_index[key] = eid
            nospace_index.setdefault(key.replace(" ", ""), key)
        return eid

    def group_entity(name: str, doc_id: str) -> str | None:
        etype, canonical = overrides.get(normalize_name(name), ("Group", name))
        eid = person_index.get(_canonical(canonical, aliases))
        if eid and g.entities[eid]["entity_type"] == "Group":
            g.docs_of[eid].add(doc_id)
            return eid
        if etype != "Group":
            return None
        eid = g.entity("Group", normalize_name(canonical), canonical, doc_id)
        person_index.setdefault(_canonical(canonical, aliases), eid)
        return eid

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for m in mentions:
        by_doc[m["document_id"]].append(m)

    for doc_id, ms in by_doc.items():
        doc = docs.get(doc_id)
        if not doc:
            continue
        year = (doc.get("published_at") or "")[:4]
        ids = doc["seed_ids"].split("|")
        doc_shows = [show_entity[i] for i in ids if i in show_entity]
        doc_seed_keys = {k: seed_entity[i] for i in ids if i in seed_entity for k in seed_keys[i]}
        from_artist_channel = not doc_shows and doc["collection_method"] != "Tìm theo tên (yt-dlp) + API"
        songs = {}
        for m in ms:
            if m["mention_type"] == "Song":
                songs[m["mention"]] = g.entity(
                    "Song", song_key(m["mention"]), m["mention"], doc_id,
                    release_year=year if doc["content_tag"] == "mv_audio" and not doc_shows else "", official_url=doc["url"] if not doc_shows else "",
                )

        def song_of(m):
            return songs.get(m["song"]) or (g.entity("Song", song_key(m["song"]), m["song"], doc_id) if m["song"] else None)

        singers_by_song: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        doc_brands: list[tuple[str, dict]] = []
        for m in ms:
            mtype, role = m["mention_type"], m["role"]
            if mtype == "Person":
                pid = person(m["mention"], doc_id, doc_seed_keys, m["location"] == "tiêu đề")
                ptype = g.entities[pid]["entity_type"] if pid else None
                # "PHAN MẠNH QUỲNH x KARIK x STING": brand đứng chung chỗ ca sĩ → nối nghệ sĩ của video với brand.
                if ptype == "Brand":
                    doc_brands.append((pid, m))
                    continue
                if ptype not in {"Person", "Group"}:
                    continue
                if role == "member_of":
                    g.relate(pid, "MEMBER_OF", group_entity(m["group"], doc_id), doc, m, "thành viên (tên kèm nhóm trong ngoặc)")
                    continue
                # "HUSTLANG Robber", "RPT MCK": tiền tố là tên crew mà nghệ sĩ thuộc về.
                crew = m["mention"].split()[0].lower() if len(m["mention"].split()) >= 2 else ""
                if crew in CREW_PREFIX:
                    g.relate(pid, "MEMBER_OF", group_entity(crew, doc_id), doc, m, "thành viên crew (tiền tố trong nghệ danh)")
                sid = song_of(m)
                if role in {"performer", "featured"} and sid:
                    g.relate(pid, "PERFORMED" if role == "performer" else "FEATURED_ON", sid, doc, m, "biểu diễn tại chương trình" if doc_shows else "trình bày")
                    singers_by_song[sid].append((pid, m))
                elif role == "composer" and sid:
                    g.relate(pid, "COMPOSED", sid, doc, m, "sáng tác/viết lời")
                elif role == "producer" and sid:
                    g.relate(pid, "PRODUCED", sid, doc, m, "sản xuất/hòa âm")
                for show_eid in doc_shows:
                    show_type = g.entities[show_eid]["entity_type"]
                    if role == "coach":
                        g.relate(pid, "JUDGE_ON", show_eid, doc, m, "huấn luyện viên")
                    elif role == "performer" and show_type == "Show" and COMPETITION.search(g.names[show_eid].most_common(1)[0][0]):
                        # Tiết mục trong playlist show thi đấu đa số là của thí sinh; khách mời cần loại khi duyệt.
                        g.relate(pid, "CONTESTANT_ON", show_eid, doc, m, "nghệ sĩ có tiết mục trong chương trình")
                    elif role == "performer":
                        g.relate(pid, "PERFORMED_AT", show_eid, doc, m, "biểu diễn tại sự kiện" if show_type == "Event" else "khách mời/nghệ sĩ biểu diễn trong chương trình")
            elif mtype == "Company":
                cid = g.entity("Company", _company_key(m["mention"]), m["mention"], doc_id)
                sid = song_of(m)
                if from_artist_channel and sid and m["role"] in RELEASE_ROLES and not NOT_LABEL.search(m["mention"]):
                    g.relate(sid, "RELEASED_BY", cid, doc, m, {"label": "hãng phát hành (℗/label)", "audio_distributor": "trang phát hành audio", "rights_owner": "chủ sở hữu bản quyền"}[role])
                for show_eid in doc_shows:
                    if m["role"] in ORGANIZER_ROLES:
                        g.relate(show_eid, "ORGANIZED_BY", cid, doc, m, {"format_owner": "đơn vị sản xuất", "format_distributor": "đơn vị phân phối"}.get(role, "chủ sở hữu bản quyền/phát sóng"))
            elif mtype == "Album":
                aid = g.entity("Album", normalize_name(m["mention"]), m["mention"], doc_id, release_year=year)
                sid = song_of(m)
                if sid:
                    g.relate(sid, "TRACK_OF", aid, doc, m, "bài trong album")
            elif mtype == "Brand":
                etype, brand = overrides.get(normalize_name(m["mention"]), ("Brand", m["mention"]))
                if etype != "Brand":
                    continue
                bid = g.entity("Brand", _org_key(brand), brand, doc_id)
                for s in ids:
                    if s in seed_entity:
                        detail = "đại sứ thương hiệu" if m["role"] == "ambassador" else f"hợp tác {m['role'].upper()}"
                        g.relate(seed_entity[s], "AMBASSADOR_OF", bid, doc, m, detail)

        for sid, singers in singers_by_song.items():
            # Danh sách "Thể hiện:" 16–20 người của liveshow/cypher không phải hợp tác cặp đôi; chỉ suy ra khi ≤ 6 người.
            if len({p for p, _ in singers}) > 6:
                continue
            for (a, ma), (b, _) in combinations(singers, 2):
                if a != b:
                    g.relate(a, "COLLABORATED_WITH", b, doc, ma, "cùng trình bày một bài", derived=True)
        artists = {p for singers in singers_by_song.values() for p, _ in singers} or {seed_entity[i] for i in ids if i in seed_entity}
        for bid, m in doc_brands:
            for p in artists:
                g.relate(p, "AMBASSADOR_OF", bid, doc, m, "hợp tác MV/quảng cáo (brand đứng tên trong tiêu đề)")

    vn_docs = {i for i, d in docs.items() if VI_CHARS.search(d.get("title", "")) or VI_CHARS.search(d.get("content", ""))}
    _prune(g, mentions, vn_docs)
    _merge_web(g)
    _write(g)


def _read_csv(path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def web_documents() -> list[dict]:
    path = WEB_GRAPH_DIR / "documents.csv"
    if not path.exists():
        return []
    # url gốc là link news.google.com; trích dẫn phải trỏ về bài báo gốc.
    return [
        {
            "document_id": d["document_id"], "url": d["final_url"] or d["resolved_url"] or d["url"], "source_name": d["source_name"], "source_type": d["source_type"],
            "title": d["title"], "published_at": d["published_at"][:10], "collected_at": d["collected_at"], "collection_method": d["collection_method"],
            "document_status": d["document_status"], "account_verified": "", "platform": "web", "content_tag": "press", "seed_ids": "",
        }
        for d in _read_csv(path)
    ]


def _merge_web(g: Graph) -> None:
    rel_path = WEB_GRAPH_DIR / "relations.csv"
    if not rel_path.exists():
        return
    docs = {d["document_id"]: d for d in web_documents()}
    evidence_of: dict[str, list[dict]] = defaultdict(list)
    for ev in _read_csv(WEB_GRAPH_DIR / "evidence.csv"):
        if ev["document_id"] in docs:
            evidence_of[ev["relation_id"]].append(ev)

    added, enriched, skipped = Counter(), Counter(), []
    for wr in _read_csv(rel_path):
        src, rtype, tgt = wr["source_entity_id"], wr["relation_type"], wr["target_entity_id"]
        evs = evidence_of[wr["relation_id"]]
        if src not in g.entities or tgt not in g.entities or not evs:
            skipped.append(f"{wr['source_name']} – {wr['target_name']}")
            continue
        if rtype in UNDIRECTED:
            src, tgt = sorted((src, tgt))
        key = (src, rtype, tgt)
        existed = key in g.relations
        for ev in evs:
            doc = docs[ev["document_id"]]
            mention = {"location": ev["sentence_location"], "quote": ev["quote"], "method": f"báo chí: {ev['extraction_method']}"}
            g.relate(src, rtype, tgt, doc, mention, "báo chí xác nhận" if existed else wr["role_detail"])
            g.evidence[(g.relations[key]["relation_id"], doc["document_id"], ev["sentence_location"])].update(
                review_status=ev["review_status"], review_note=ev["review_note"], confidence_score=ev["confidence_score"],
            )
            g.docs_of[src].add(doc["document_id"])
            g.docs_of[tgt].add(doc["document_id"])
        rel = g.relations[key]
        rel["notes"] = "có bằng chứng báo chí"
        if wr["verification_status"] == VERIFIED:
            rel["verification_status"] = VERIFIED
        (enriched if existed else added)[rtype] += 1
    print(f"Gộp graph báo chí ({WEB_GRAPH_DIR.name}): cạnh mới {dict(added)}, cạnh có sẵn thêm bằng chứng {dict(enriched)}")
    if skipped:
        print(f"  Bỏ qua {len(skipped)} cạnh vì nút đã bị lọc khỏi graph tổng: {', '.join(skipped)}")


def _prune(g: Graph, mentions: list[dict], vn_docs: set[str]) -> None:
    """Bỏ node rác còn sót sau quy tắc: nhạc sĩ nước ngoài của bài cover, từ thường một chữ chỉ gặp một lần."""
    # Âm tiết tên Việt học từ chính dữ liệu: mọi chữ của tên/bài có dấu, đổi về không dấu.
    vi_syllables = {
        normalize_name(t) for m in mentions if m["mention_type"] in {"Person", "Song"} and _has_accent(m["mention"]) for t in m["mention"].split()
    }
    song_words = Counter(unicodedata.normalize("NFC", t).casefold() for m in mentions if m["mention_type"] == "Song" for t in m["mention"].split())
    relations_of: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for (src, rtype, tgt) in g.relations:
        relations_of[src].add((rtype, tgt))
        relations_of[tgt].add((rtype, src))
    verified = {eid for eid, e in g.entities.items() if e.get("seed_id")}
    performed_by: dict[str, set[str]] = defaultdict(set)
    for (src, rtype, tgt) in g.relations:
        if rtype in {"PERFORMED", "FEATURED_ON"}:
            performed_by[tgt].add(src)

    drop = set()
    for eid, e in g.entities.items():
        if e["entity_type"] not in {"Person", "Group"} or e.get("seed_id"):
            continue
        # Người ngoài seeds chỉ có mặt trong video không có chữ Việt (EDM quốc tế trên kênh WUKONG) thì ngoài phạm vi nhạc Việt.
        if not g.docs_of[eid] & vn_docs:
            drop.add(eid)
            continue
        name = g.names[eid].most_common(1)[0][0]
        tokens = name.split()
        # Tên nước ngoài: không dấu, đa số âm tiết không phải âm tiết tên Việt (Alan Menken, Jun Jie Wayne Lim).
        foreign = len(tokens) >= 2 and not _has_accent(name) and sum(normalize_name(t) in vi_syllables for t in tokens) * 2 < len(tokens)
        # Producer người Việt nghệ danh tiếng Anh (Justin TechN9) xuất hiện nhiều video; nhạc sĩ gốc của bài cover thì chỉ 1–2 lần.
        if foreign and len(g.docs_of[eid]) < 3:
            # Giữ người nước ngoài hợp tác trực tiếp với nghệ sĩ Việt (Sơn Tùng ft. Tyga); bỏ nhạc sĩ/producer của bài cover.
            direct = any(
                (rtype == "COLLABORATED_WITH" and other in verified) or (rtype in {"PERFORMED", "FEATURED_ON"} and performed_by[other] & verified)
                for rtype, other in relations_of[eid]
            )
            if not direct:
                drop.add(eid)
                continue
        # Họ đứng một mình ("ĐỖ", "Ha") là mảnh tên bị cắt.
        if len(tokens) == 1 and normalize_name(name) in VI_SURNAMES:
            drop.add(eid)
            continue
        # Tên tiếng Việt ≥3 chữ bắt đầu bằng họ; chữ đầu có dấu mà không phải họ ("BƯỚC QUA MÙA CÔ ĐƠN", "Đường Một Chiều") là cụm từ.
        # So có dấu vì bỏ dấu thì "Đường" trùng "Dương"; chữ đầu không dấu là nghệ danh (Wanbi Tuấn Anh, JB Lê Phương) nên giữ.
        first = tokens[0].casefold()
        # Nghệ danh kèm ký hiệu ("Ngọc Anh 3A", "Thế Phương VBK") không phải cụm từ.
        tagged = any(any(ch.isdigit() for ch in t) or (not _has_accent(t) and song_words[t.casefold()] == 0) for t in tokens)
        if len(tokens) >= 3 and not tagged and _has_accent(tokens[0]) and first not in VI_SURNAMES_ACCENTED and tokens[-1].casefold() not in VI_SURNAMES_ACCENTED:
            drop.add(eid)
            continue
        # Từ một chữ có dấu chỉ gặp một lần, hoặc hay gặp trong tên bài ("Những", "Bác", "Còn"), là từ thường, không phải nghệ danh.
        common_word = song_words[name.casefold()] >= 5
        if len(tokens) == 1 and _has_accent(name) and not name.isupper() and (len(g.docs_of[eid]) <= 1 or common_word):
            drop.add(eid)

    # HLV/giám khảo của một show ("Team Rhymastic") không đồng thời là thí sinh của show đó.
    # HLV/giám khảo ở bất kỳ mùa nào của cùng chương trình (theo "Team X" hoặc seeds/show_roles.csv) không phải thí sinh.
    show_family = {eid: normalize_name(re.sub(r"\s+(?:mùa \d+|\d{4})$", "", g.names[eid].most_common(1)[0][0])) for eid, e in g.entities.items() if e["entity_type"] in {"Show", "Event"}}
    judge_keys = {(g.keys.get(src), show_family.get(tgt)) for (src, rtype, tgt) in g.relations if rtype == "JUDGE_ON"} | load_show_roles()
    stale = [
        k for k in g.relations
        if k[0] in drop or k[2] in drop or (k[1] == "CONTESTANT_ON" and (g.keys.get(k[0]), show_family.get(k[2])) in judge_keys)
    ]
    dropped_rels = {g.relations.pop(k)["relation_id"] for k in stale}
    g.evidence = {k: ev for k, ev in g.evidence.items() if ev["relation_id"] not in dropped_rels}
    for eid in drop:
        g.entities.pop(eid, None)
    print(f"Lọc thêm {len(drop)} node (nhạc sĩ nước ngoài của bài cover, từ thường một chữ)")


def _write(g: Graph) -> None:
    n_rel: Counter = Counter()
    for (src, _, tgt) in g.relations:
        n_rel[src] += 1
        n_rel[tgt] += 1
    for eid, e in g.entities.items():
        names = g.names[eid]
        e["canonical_name"] = g.fixed_name.get(eid) or (e["entity_type"] == "Company" and COMPANY_DISPLAY.get(g.keys.get(eid, ""))) or _display(names)
        e["aliases"] = " | ".join(sorted(n for n in names if n and n != e["canonical_name"]))
        e["n_documents"] = len(g.docs_of[eid])
        e["n_relations"] = n_rel[eid]
    for rel in g.relations.values():
        rel["role_detail"] = "; ".join(sorted(rel["role_detail"]))
        rel["source_name"] = g.entities[rel["source_entity_id"]]["canonical_name"]
        rel["target_name"] = g.entities[rel["target_entity_id"]]["canonical_name"]
        rel["n_documents"] = len(rel.pop("docs"))

    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    for name, columns, rows in [
        ("entities.csv", ENTITY_COLUMNS, sorted(g.entities.values(), key=lambda e: e["entity_id"])),
        ("relations.csv", RELATION_COLUMNS, sorted(g.relations.values(), key=lambda r: r["relation_id"])),
        ("evidence.csv", EVIDENCE_COLUMNS, sorted(g.evidence.values(), key=lambda r: r["evidence_id"])),
    ]:
        with (GRAPH_DIR / name).open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns)
            w.writeheader()
            w.writerows(rows)
    g.reg.save()

    connected = [e for e in g.entities.values() if e["n_relations"]]
    print(f"Đã ghi bảng Entity/Relation/Evidence → {GRAPH_DIR} ({now_iso()})")
    print(f"Node: {len(g.entities)} (có ít nhất 1 cạnh: {len(connected)})")
    print("  theo loại:", dict(Counter(e["entity_type"] for e in g.entities.values()).most_common()))
    print("  có cạnh theo loại:", dict(Counter(e["entity_type"] for e in connected).most_common()))
    print("  theo trạng thái:", dict(Counter(e["verification_status"] for e in g.entities.values())))
    print(f"Cạnh: {len(g.relations)} | bằng chứng: {len(g.evidence)}")
    print("  theo loại quan hệ:", dict(Counter(r["relation_type"] for r in g.relations.values()).most_common()))
