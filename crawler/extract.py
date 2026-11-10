import csv
import re
import unicodedata
from collections import Counter, defaultdict

from .common import normalize_name, now_iso, read_seeds
from .config import INTERIM_DIR, SEEDS_PATH
from .layer1 import DASH, SHOW_WORDS, _clean, _key, _names, _songs, parse_title
from .layer1_extract import _write_preserving_review, org_mentions
from .scope import VI_CHARS
from .shows import read_shows

DOCUMENTS_PATH = INTERIM_DIR / "documents.csv"
MENTIONS_PATH = INTERIM_DIR / "mentions.csv"
HANDLES_PATH = INTERIM_DIR / "social_handles.csv"
MENTION_COLUMNS = ["document_id", "seed_ids", "content_tag", "mention", "mention_type", "role", "song", "group", "location", "quote", "method"]
OVERRIDES_PATH = SEEDS_PATH.with_name("entity_overrides.csv")
# "THƠM (Da LAB)", "Kata Trần (DTAP)": tên người kèm nhóm trong ngoặc.
AFFILIATION = re.compile(r"([^,()\[\]|:;\n]{2,40}?)\s*\(([^()\[\]\n]{2,30})\)")

FEAT = re.compile(r"\s*[(\[]?\s*\b(?:ft|feat|featuring)\b\.?\s*", re.IGNORECASE)
TAIL_NOISE = re.compile(
    r"\s*\b(?:official\s+)?(?:music video|m/?v|lyrics? video|lyrics?|visualizer|audio|special clip|teaser|performance video|dance practice)\b\.?\s*$",
    re.IGNORECASE,
)
SEG_NOISE = re.compile(
    r"^(?:official|offical|ost\b.*|prod\b.*|live\b.*|acoustic\b.*|remix|cover|\d{4}|#.*|.*\b(?:music video|m/?v|lyrics?|visualizer|audio)\b.*)$",
    re.IGNORECASE,
)
# Video gộp nhiều bài: credit trong mô tả không biết thuộc bài nào nên không gán.
COMPILATION = re.compile(r"liên khúc|\blk\b|playlist|tuyển tập|tuyển chọn|full album|album experience|\btop \d+|\d+ (?:bài|ca khúc)|nonstop|mashup|medley", re.IGNORECASE)
MULTI_SONG_VIDEO = re.compile(
    r"liên khúc|\blk\b|playlist|tuyển tập|tuyển chọn|\btop \d+|\d+ (?:bài|ca khúc)|nonstop|nhạc (?:tết|xuân) \d{4}|"
    r"cover (?:các|những|loạt) (?:bài|ca khúc|hit)|các bài hit|tổng hợp",
    re.IGNORECASE,
)
COVER = re.compile(r"\bcover\b", re.IGNORECASE)
# "(Andree ft Lee7)" sau tên bài: ghi ca sĩ gốc, không phải khách mời của video.
ORIGINAL_CREDIT = re.compile(r"\((?!\s*(?:ft|feat|featuring)\b)(?=[^)]*\b(?:ft|feat|featuring)\b)[^)]*\)", re.IGNORECASE)
NOT_SONG = re.compile(
    r"vlog|reaction|behind|hậu trường|teaser|trailer|tập \d+|episode|livestream|phỏng vấn|interview|karaoke|beat|uncut|highlight|recap|\bbts\b|^full$",
    re.IGNORECASE,
)
PROD = re.compile(r"\s*[(\[]?\s*\bprod(?:uced)?\b\.?\s*(?:by\s+)?([^)\]|]+?)\s*[)\]]?\s*$", re.IGNORECASE)
ALBUM = re.compile(r"^(?:album|ep)\b(?![.\s]*\d)\s*[:\-–]?\s*(.+)$", re.IGNORECASE)
ALBUM_TAIL = re.compile(r"\s*[-–]?\s*track\s*(?:no\.?)?\s*\d+$|\s*\(\d{4}\)$", re.IGNORECASE)
LEGAL_SUFFIX = {"llc", "limited liability company", "ltd", "co ltd", "jsc", "inc", "pte ltd", "corp"}
TRACK_NO = re.compile(r"^(?:track\s*(?:no\.?)?\s*\d+|\d{1,2}[.)])\s*[-–:.]?\s*", re.IGNORECASE)
FULL_ALBUM = re.compile(r"full album|album experience", re.IGNORECASE)

ROLE_PREFIX = re.compile(
    r"^(?:(?:music producer|vocal producer|producer|singer|sáng tác|composer|songwriter|lyricist|editing|editor|artists?|lời việt)\s*[:：.]?|(?:st|việt|nhạc|rap)\s*[:：.])\s+",
    re.IGNORECASE,
)
ROLE_WORDS = {"manager", "artist manager", "guitar", "bass", "drums", "music producer", "composer", "singer", "artist", "artists", "songwriter", "lyricist", "arranger", "nha san xuat", "ca si", "nhac si", "rapper"}
JUNK_PERSON = re.compile(r"[|:#@]|\b(?:official|audio|cover|live|music producer|nhạc hoa|channel|records?|team|band ver|anh tài|chị đẹp|nhóm|đội)\b", re.IGNORECASE)

COMPANY_WORDS = re.compile(r"entertainment|\bent\b|records?|music|media|network|studios?|jsc|label|company|corp|công ty|production|agency|holdings?|group", re.IGNORECASE)
ENT_WORDS = re.compile(r"giải trí|truyền thông|âm nhạc|nghệ thuật|entertainment|media|music|records?|recordings|production|studios?|label|network|đĩa|international|collective", re.IGNORECASE)
GENERIC_ORG = {"truyen thong", "dau tu", "giai tri", "giai tri dv", "truyen thong giai tri", "am nhac", "san xuat"}
LABEL = re.compile(
    r"(?:℗\s*(?:\d{4}\s*)?|(?i:(?:record )?label\s*[:：]|released by|phát hành bởi|distributed by|độc quyền bởi)\s*[:：]?\s*)([A-Z0-9Đ][\w&.'’ -]{1,60})"
)
BRAND_NAME = r"([A-ZĐ][\w&+.'’-]*(?: [A-ZĐ0-9][\w&+.'’-]*){0,3})"
BRAND_PATTERNS = [
    ("ambassador", re.compile(r"(?i:đại sứ (?:thương hiệu|hình ảnh|toàn cầu)(?: của| cho)?|brand ambassador(?: of| for)?|ambassador (?:of|for))\s+" + BRAND_NAME)),
    ("tvc", re.compile(r"(?i:\btvc)\s+" + BRAND_NAME)),
    ("campaign", re.compile(r"\(\s*" + BRAND_NAME + r"\s+(?i:campaign)\s*\)|\|\s*" + BRAND_NAME + r"\s+(?i:campaign)\b")),
]

SOCIAL = {
    "facebook": re.compile(
        r"(?:facebook|fb)\.com/(?!watch|share|sharer|groups/|events/|hashtag|photo|permalink|story|pages/|people/|plugins|login|reel/|videos?/)"
        r"(profile\.php\?id=\d+|[A-Za-z0-9.\-_]{3,80})",
        re.IGNORECASE,
    ),
    "instagram": re.compile(r"instagram\.com/(?!p/|reel/|reels/|explore|stories|tv/|accounts)([A-Za-z0-9._]{2,30})", re.IGNORECASE),
    "tiktok": re.compile(r"tiktok\.com/@([A-Za-z0-9._]{2,30})", re.IGNORECASE),
    "spotify": re.compile(r"open\.spotify\.com/(?:intl-\w+/)?artist/([A-Za-z0-9]{22})"),
    "threads": re.compile(r"threads\.(?:net|com)/@([A-Za-z0-9._]{2,30})", re.IGNORECASE),
}
SOCIAL_URL = {
    "facebook": "https://www.facebook.com/{}",
    "instagram": "https://www.instagram.com/{}",
    "tiktok": "https://www.tiktok.com/@{}",
    "spotify": "https://open.spotify.com/artist/{}",
    "threads": "https://www.threads.net/@{}",
}


def _has_name(text: str, keys: set[str]) -> bool:
    padded = f" {normalize_name(text)} "
    return any(f" {k} " in padded for k in keys)


def _split_feat(part: str) -> tuple[str, str]:
    pieces = FEAT.split(part, maxsplit=1)
    return pieces[0].strip(), (pieces[1].strip(" )]") if len(pieces) > 1 else "")


QUOTES = "\"'“”‘’「」『』"
ALBUM_SUFFIX = re.compile(
    r"\s*[(\[]?\s*(?:full\s+(?:album|ep)(?:\s+experience)?|(?:album|ep)\s+experience|full experience|full track|highlight medley|album highlight|"
    r"one-click|full album/one-click|coming soon|the \d+(?:st|nd|rd|th) album|trailer(?:\s*#\d+)?|deluxe)\s*[)\]]?\s*$",
    re.IGNORECASE,
)
NOT_ALBUM = re.compile(
    r"snippet|recap|spoiler|release party|hành trình|trailer|hay nhất|nhạc trẻ|những ca khúc|tuyển tập|^vol\.?\s*\d+$|^part\s*\d|liên quân|\d{4}$",
    re.IGNORECASE,
)
FOREIGN_SCRIPT = re.compile(r"[Ѐ-ӿ฀-๿ᄀ-ᇿ぀-ヿ㐀-鿿가-힯]")


ALBUM_NOISE = re.compile(
    r"[(\[]?\s*(?:the\s+)?full\s+(?:album|ep)(?:\s+experience)?\s*[)\]]?|[(\[]\s*prod[^)\]]*[)\]]|^\s*deluxe\b|^\s*vol\.?\s*\d+\b|\s+[-–]\s+.*$|:\s*the$",
    re.IGNORECASE,
)


def _album_name(raw: str) -> str:
    name = ALBUM_NOISE.sub(" ", raw.strip())
    # Giữ dấu nháy giữa từ (Cam'On, Party's); bỏ ngoặc kép lệch ở bất kỳ đâu.
    name = re.sub(r"(?<!\w)['’]|['’](?!\w)", " ", re.sub(r"[\"“”‘「」『』•·]", " ", name))
    name = " ".join(re.sub(r"(?i)\(sped up\)", " ", name).split()).strip(" .-–:/")
    for _ in range(3):
        name = ALBUM_SUFFIX.sub("", ALBUM_TAIL.sub("", name)).strip(" -–/" + QUOTES)
        name = re.sub(r"\s*\b(?:album|ep)$", "", name, flags=re.IGNORECASE).strip(" -–" + QUOTES)
    # `TÌNH" - Nói Với Bản Thân`: phần sau dấu đóng ngoặc là tên bài, không thuộc tên album.
    name = re.split(r"[\"”’]\s*[-–(]", name)[0].strip(" -–" + QUOTES)
    if not name or len(name.split()) > 8 or NOT_ALBUM.search(name) or FOREIGN_SCRIPT.search(name):
        return ""
    return name


MASHUP_START = re.compile(r"^\s*(?:mashup|medley|liên khúc|lk)\b", re.IGNORECASE)
PAREN = re.compile(r"[(\[][^)\]]*[)\]]")
REMIX_PAREN = re.compile(r"[(\[][^)\]]*\b(?:remix|edit|flip|bootleg|version|ver\.?|mix)\b[^)\]]*[)\]]", re.IGNORECASE)


def _parse_song_first(title: str) -> tuple[list[tuple[str, str]], list[str], bool]:
    segments = [s.strip() for s in _clean(title).split("|") if s.strip()]
    if len(segments) < 2:
        return [], [], False
    songs, mashup = _songs(segments[0])
    return [(n, "performer") for n in _names(segments[1])], songs, mashup


NOT_SONG_TITLE = re.compile(
    r"hay nhất|siêu phẩm|phần \d|khui quà|sinh nhật|birthday|chill at home|chủ đề|liveclip|sổ tay|mới nhất|nhạc (?:vàng|trẻ|trữ tình|bolero)|^(?:ep|vol)\.?\s*\d|"
    r"＠|@|award|challenge|setup|thiết bị|documentary|motor show|festival|fesival|\bpart \d|\bp\d+$|^st\s*:|^(?:piano|acoustic) version$|^making$|"
    r"^màn\s|fan ?meeting|focus cam|in da house|^remix\b|\bby$",
    re.IGNORECASE,
)
MUSIC_TITLE = re.compile(
    r"\b(?:m/?v|music video|official|offical|lyrics?|audio|visualizer|ost|acoustic|cover|remix|live|ft\.?|feat\.?|prod\.?|album|ep|single|mashup|performance)\b",
    re.IGNORECASE,
)
MUSIC_DESC = re.compile(r"lnk\.to|open\.spotify|spotify\.com|music\.apple|apple music|zingmp3|zing mp3|nhaccuatui|soundcloud|℗", re.IGNORECASE)
NOT_SONG_TOPIC = re.compile(
    r"making of|how we made|ký sự|du lịch|vlog|d-log|top hit|nhạc trap|nhạc trung|full show|\bmiss\s|^cách\s|hành trình|xu hướng|korean version|"
    r"^(?:intro|outro)$|\b(?:ep|album)$|giảm cân|chuyện tối nay|nhồi thịt|đi chùa|minh họa|lá thư gửi|sắp nổi tiếng",
    re.IGNORECASE,
)
SONG_TAIL = re.compile(r"\s*(?:\b(?:feat|ft)\.?|\bdemo|dance practice.*|acoustic show|\bremix(?: by .*)?)$", re.IGNORECASE)
NON_MUSIC_TITLE = re.compile(r"\bhài\b|sitcom|web ?drama|phim ngắn|short film|parody|fan ?meeting|tiểu phẩm", re.IGNORECASE)


def clean_song(name: str, known_people: frozenset[str] = frozenset()) -> str:
    # Bản remix/phiên bản gộp về bài gốc để không tách thành nhiều node Song.
    name = REMIX_PAREN.sub("", re.sub(r"\s*#\S+", "", name))
    name = TRACK_NO.sub("", name.strip()).strip(" -–" + QUOTES)
    name = re.sub(r"\s+[lI]$", "", name)
    name = SONG_TAIL.sub("", name).strip(" -–" + QUOTES)
    # Ngoặc kép lệch còn sót giữa tên ("Hít "Drama") được bỏ.
    if name.count('"') % 2 or name.count("“") != name.count("”"):
        name = re.sub(r"[\"“”]", "", name).strip()
    if re.fullmatch(r"(?i)official\s+(?:intro|outro)", name):
        return ""
    if known_people and normalize_name(name) in known_people:
        return ""
    if not name or len(name) > 60 or len(name.split()) > 10 or NOT_SONG.search(name) or NOT_SONG_TITLE.search(name) or NOT_SONG_TOPIC.search(name):
        return ""
    if FOREIGN_SCRIPT.search(name) and not re.search(r"[A-Za-zÀ-ỹ]{2}", FOREIGN_SCRIPT.sub("", name)):
        return ""
    # "REX, HIEUTHUHAI, MANBO" hay "Nguyễn Kiều Anh": vế tiêu đề toàn tên người, không phải tên bài.
    parts = [normalize_name(p) for p in re.split(r"\s*[,&]\s*", name) if p.strip()]
    if known_people and parts and all(p in known_people for p in parts):
        return ""
    return name


def _take_prod(text: str) -> tuple[str, list[str]]:
    m = PROD.search(text)
    if not m:
        return text, []
    return text[: m.start()], [n for n in map(clean_person, _names(m.group(1))) if n]


PERSON_TITLE = re.compile(r"^(?:guitarist|bassist|drummer|pianist|saxophone|violinist|mentor|diva|bé|thơ|nghệ sĩ|ns|nsưt|nsnd|ca sĩ|nhạc sĩ|rapper|producer)\s+", re.IGNORECASE)
# Từ chỉ tổ chức, phiên bản hoặc nội dung vlog: tên chứa chúng không phải tên người.
NOT_PERSON_WORDS = re.compile(
    r"\b(?:studios?|productions?|records?|recordings|entertainment|media|music|label|mobile|company|corp|official|version|remix|lofi|"
    r"cooking|thử thách|ost|dân ca|classroom|division|channel|garena|việt nam|vietnam|awards?|wechoice|beat|hiphop|greatest hits|project|fc|offline|mix|piano|flute|hoạt hình|phim|universe|cover|audio|live|team|nhóm|đội|anh tài|chị đẹp|band ver|nhạc hoa|music producer|"
    r"fan'?s?|meeting|focus|cam|family|show|tập|trình diễn|mashup|đập|card|của|collection|recap|mới nhất|\d(?:st|nd|rd|th))\b",
    re.IGNORECASE,
)
GENERIC_PERSON = {"bai hat", "all", "phim", "lon", "man", "bai", "dien", "cua gio", "co ta", "i do", "jr", "tn", "kk", "performers", "performer", "mixed", "nguon", "lan", "mentor", "singer", "rap", "vocal", "vocals", "chorus", "dan", "piano", "guitar"}
NAME_CHARS = re.compile(r"^[\wÀ-ỹ.\-&$'’ ]+$")


def clean_person(name: str) -> str:
    name = TRACK_NO.sub("", name.strip()).lstrip("•·*►▶✪★☆ ")
    for _ in range(2):
        name = ROLE_PREFIX.sub("", name.strip(" .:;-–" + QUOTES))
        name = PERSON_TITLE.sub("", name)
    tokens = name.split()
    if len(tokens) >= 2 and tokens[-1] in {"I", "l"}:
        tokens = tokens[:-1]
        name = " ".join(tokens)
    key = normalize_name(name)
    if not tokens or key in ROLE_WORDS or key in GENERIC_PERSON or len(tokens) > 5:
        return ""
    if not NAME_CHARS.match(name) or FOREIGN_SCRIPT.search(name) or NOT_PERSON_WORDS.search(name):
        return ""
    if any(len(t) > 20 for t in tokens) or (len(tokens) >= 3 and all(len(t) == 1 for t in tokens)):
        return ""
    # "VẾT MƯA I HÀ ANH TUẤN": chữ I đứng giữa là dấu phân cách tiêu đề.
    if len(tokens) >= 3 and "I" in tokens[1:-1]:
        return ""
    # Tên viết hoa chữ đầu nhưng có từ sau viết thường là mảnh câu ("Quốc Thiên cầu", "Karik nấu").
    if tokens[0][0].isupper() and any(t[0].isalpha() and t[0].islower() for t in tokens[1:]):
        return ""
    return name


def parse_artist_title(title: str, artist_keys: set[str], known_people: frozenset[str] = frozenset()) -> dict[str, list[str]]:
    """Trả {performer, featured, producer, song, album} từ tiêu đề video trên kênh nghệ sĩ; cần thấy tên nghệ sĩ để biết vế nào là bài hát."""
    out: dict[str, list[str]] = {"performer": [], "featured": [], "producer": [], "song": [], "album": []}
    if MULTI_SONG_VIDEO.search(title) or NON_MUSIC_TITLE.search(title):
        return out
    segments = [TAIL_NOISE.sub("", s).strip(" -–") for s in _clean(title).split("|")]
    album_segs = [_album_name(m.group(1)) for s in segments if (m := ALBUM.match(s.strip()))]
    segments = [s for s in segments if s and not SEG_NOISE.match(s) and not ALBUM.match(s.strip())]
    artist_part = song_part = ""
    for seg in segments:
        parts = [p.strip() for p in DASH.split(seg) if p.strip()]
        if len(parts) < 2:
            continue
        # "VIỆT ANH - Đức Kaishi - Trung Ngon - HÃY QUÊN ANH ĐI": vế không chứa người đã biết là bài, các vế còn lại là nghệ sĩ.
        if len(parts) > 2:
            unknown = [i for i, p in enumerate(parts) if not _has_name(p, artist_keys | known_people)]
            if len(unknown) == 1:
                song_i = unknown[0]
                parts = [" x ".join(p for i, p in enumerate(parts) if i != song_i), parts[song_i]]
        # Ưu tiên vế có tên nghệ sĩ ở phần chính, ngoài ngoặc và ngoài đoạn ft.; "(CM1X REMIX)" nằm ở vế bài hát.
        main = [PAREN.sub(" ", _split_feat(p)[0]) for p in parts[:2]]
        side = next((i for i in (0, 1) if _has_name(main[i], artist_keys)), None)
        if side is None and any(_has_name(p, artist_keys) for p in parts[:2]):
            side = next((i for i in (0, 1) if _has_name(main[i], known_people)), None)
            if side is None:
                remix_side = next((i for i in (0, 1) if REMIX_PAREN.search(parts[i]) and _has_name(parts[i], artist_keys)), None)
                side = 1 - remix_side if remix_side is not None else 0
        if side is not None:
            artist_part, song_part = parts[side], parts[1 - side]
            break
    if not artist_part:
        side = next((i for i, s in enumerate(segments) if len(s) <= 60 and _has_name(s, artist_keys) and _names(s)), None)
        rest = [s for i, s in enumerate(segments) if i != side and not SHOW_WORDS.search(s) and not _has_name(s, artist_keys) and not DASH.search(s)]
        if side is None:
            return out
        artist_part, song_part = segments[side], (rest[0] if rest else "")
    artist_main, artist_feat = _split_feat(artist_part)
    song_part = ORIGINAL_CREDIT.sub(" ", song_part)
    song_main, song_feat = _split_feat(song_part)
    # Video cover: "ft." ở vế bài hát là của bản gốc, người trong video chỉ là người cover.
    if COVER.search(title):
        song_feat = ""
    song_main, prod_main = _take_prod(song_main)
    song_feat, prod_feat = _take_prod(song_feat)
    out["producer"] = prod_main + prod_feat
    song_main = TAIL_NOISE.sub("", song_main).strip(" -–\"'“”‘’")
    for m in REMIX_PAREN.finditer(song_main):
        remixers = re.sub(r"(?i)\b(?:remix|edit|flip|bootleg|version|ver\.?|mix)\b", " ", m.group(0)[1:-1])
        out["producer"] += [n for n in map(clean_person, _names(remixers)) if n]
    song_main = REMIX_PAREN.sub("", song_main).strip(" -–" + QUOTES)
    out["performer"] = [n for n in map(clean_person, _names(artist_main)) if n]
    out["featured"] = [n for n in map(clean_person, _names(artist_feat) + _names(song_feat)) if n]
    out["album"] = [a for a in album_segs if a]
    album_in_song = ALBUM.match(song_main)
    if song_main and (FULL_ALBUM.search(title) or album_in_song):
        album = _album_name(album_in_song.group(1) if album_in_song else song_main)
        out["album"] += [album] if album else []
    elif song_main and not (SHOW_WORDS.search(song_main) or _has_name(song_main, artist_keys)):
        out["song"] = [s for s in (clean_song(x, known_people) for x in _songs(song_main)[0]) if s]
    return out


CREW_WORDS = re.compile(
    r"\b(?:coordinator|assistants?|manager|licensing|partners?|director|producer|operations|team|của|tại|aka|official\w*)\b|^studio$|^records?$", re.IGNORECASE
)
ORG_CUT = re.compile(r"\s*(?:\(|,|\.\s|\s-\s|☞|\||\s+tại\s|\s+at\s|\s+của\s|\s+cùng\s|\s+và\s|\s+and\s|\s*&\s*|và(?=\s*[A-ZĐ]))")


def _company_name(raw: str) -> str:
    name = ORG_CUT.split(re.sub(r"^\d{4}\s*", "", raw.strip()))[0].strip(" .:;" + QUOTES)
    name = re.sub(r"\s+\d{4}$", "", name)
    if not (2 <= len(name) <= 50) or name.isdigit() or len(name.split()) > 6:
        return ""
    if normalize_name(name) in LEGAL_SUFFIX | {"all rights reserved", "copyright"} or CREW_WORDS.search(name):
        return ""
    return name


def _companies(desc: str, self_keys: set[str]) -> list[tuple[str, str, str]]:
    """Trả [(tên, vai trò, câu)] cho công ty/label; bỏ dòng © mà chủ sở hữu chính là nghệ sĩ hoặc kênh."""
    found = []
    for raw, org_type, role, quote in org_mentions(desc):
        name = _company_name(raw)
        if org_type != "Company" or not name or raw.endswith("(lnk.to)") or normalize_name(name) in self_keys:
            continue
        rest = normalize_name(re.sub(r"(?i)^công ty(?: cổ phần| tnhh)?\s*", "", name))
        # Công ty không có chữ giải trí/âm nhạc/media… thường là nhà tài trợ hoặc dịch vụ, không phải label.
        if role != "audio_distributor" and (not ENT_WORDS.search(name) or rest in GENERIC_ORG):
            continue
        found.append((name, role, quote))
    for line in unicodedata.normalize("NFC", desc or "").splitlines():
        if re.search(r"email|hotline|liên hệ|booking", line, re.IGNORECASE):
            continue
        for m in LABEL.finditer(line):
            name = _company_name(m.group(1))
            # Dòng ℗ ghi tên người (nghệ sĩ tự phát hành) không tạo Company.
            words = name.split()
            person_like = not ENT_WORDS.search(name) and 2 <= len(words) <= 3 and all(w[:1].isupper() and not w.isupper() for w in words)
            if name and not person_like and normalize_name(name) not in self_keys:
                found.append((name, "label", line.strip()[:200]))
    return found


def _brands(title: str, desc: str, artist_keys: set[str]) -> list[tuple[str, str, str, str]]:
    found = []
    for location, text in [("tiêu đề", title)] + [(f"mô tả dòng {i}", l) for i, l in enumerate((desc or "").splitlines(), 1)]:
        for role, pat in BRAND_PATTERNS:
            for m in pat.finditer(text):
                name = next(g for g in m.groups() if g).strip(" .")
                if len(name) >= 2 and not _has_name(name, artist_keys):
                    found.append((name, role, location, text.strip()[:200]))
    return found


def load_known_groups(seeds: dict) -> dict[str, str]:
    """{khóa tên: tên hiển thị} của nhóm đã biết: Group trong seeds và trong entity_overrides.csv."""
    groups = {normalize_name(s["name"]): s["name"] for s in seeds.values() if s["entity_type"] == "Group"}
    if OVERRIDES_PATH.exists():
        with OVERRIDES_PATH.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("entity_type", "").strip() == "Group":
                    groups[normalize_name(r["name"])] = (r.get("canonical_name") or r["name"]).strip()
    return groups


def affiliations(title: str, desc: str, known_groups: dict[str, str]) -> list[tuple[str, str, str, str]]:
    """Trả [(người, nhóm, vị trí, câu)] cho cụm "Tên (Nhóm)" khi nhóm là nhóm đã biết."""
    found = []
    lines = [("tiêu đề", title)] + [(f"mô tả dòng {i}", l) for i, l in enumerate((desc or "").splitlines(), 1)]
    for location, line in lines:
        for m in AFFILIATION.finditer(unicodedata.normalize("NFC", line)):
            group = known_groups.get(normalize_name(m.group(2)))
            if not group:
                continue
            # "Trình bày: THƠM (Da LAB)", "A, B, Kata Trần (DTAP)": lấy tên ngay trước ngoặc.
            before = m.group(1).split(":")[-1]
            pieces = [p for p in VALUE_SPLIT.split(before) if p.strip()]
            name = clean_person(pieces[-1]) if pieces else ""
            if name and normalize_name(name) != normalize_name(group):
                found.append((name, group, location, line.strip()[:200]))
    return found


def excluded_keys() -> set[str]:
    path = SEEDS_PATH.with_name("excluded_seeds.csv")
    if not path.exists():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {normalize_name(r["name"]) for r in csv.DictReader(f) if normalize_name(r.get("name", ""))}


CREDIT_LABELS = [
    ("performer", r"trình bày|thể hiện|ca sĩ|giọng ca|performed by|performers?|vocals?|singers?|artists?"),
    ("composer", r"sáng tác(?: mới)?|nhạc sĩ|composers?|songwriters?|song ?writers?|lyricists?|written by|tác giả|nhạc|nhạc và lời|lời(?: việt| rap)?(?: mới)?|music (?:&|and) lyrics"),
    ("producer", r"(?:music |vocal )?producers?|produced by|prod(?:\.|uced)?(?: by)?|hòa âm(?: phối khí)?|phối khí|arrangers?|arranged by|arrangement|beatmakers?|beat by"),
]
_LABEL_ROLE = [(role, re.compile(rf"(?:{pat})", re.IGNORECASE)) for role, pat in CREDIT_LABELS]
LABEL_SPLIT = re.compile(r"\s*(?:&|/|,|\band\b|\bvà\b|\+)\s*", re.IGNORECASE)
# Chỗ một cặp "nhãn: tên" kết thúc và cặp sau bắt đầu: "Nhạc: A - Lời: B", "TRÌNH BÀY: X *DSP: Y".
NEXT_PAIR = re.compile(r"\s*(?:\s[*•|►]|\s[-–]\s|;)\s*(?=[^:：*•|►\n]{2,40}[:：])")
VALUE_SPLIT = re.compile(r"\s*(?:,|&|\+|/|;|\s[-–]\s|\bf\.t\.?|\bft\.?|\bfeat\.?|\bfeaturing\b|\s[xX×]\s|\bvà\b|\bwith\b)\s*", re.IGNORECASE)


def _label_roles(label: str) -> list[str]:
    """Mọi phần của nhãn phải là vai trò âm nhạc; "Music Director", "Executive Producer" không khớp nên bị bỏ."""
    parts = [p for p in LABEL_SPLIT.split(label.strip(" .-–*•►▶✪★☆#").lower()) if p]
    roles = []
    for part in parts:
        role = next((r for r, pat in _LABEL_ROLE if pat.fullmatch(part)), None)
        if role is None:
            return []
        roles.append(role)
    return list(dict.fromkeys(roles))


def credit_lines(desc: str) -> list[tuple[str, str, int, str]]:
    """Trả [(tên, vai trò, số dòng, dòng gốc)] từ các dòng "Nhãn: Tên" trong mô tả."""
    found = []
    for line_no, line in enumerate(unicodedata.normalize("NFC", desc or "").splitlines(), 1):
        rest = line.strip()
        if not rest or rest.startswith("#") or "http" in rest.split(":")[0]:
            continue
        while rest:
            m = re.match(r"^[\W_]*([^:：]{2,40}?)\s*[:：]\s*(.*)$", rest)
            if not m:
                break
            label, tail = m.groups()
            nxt = NEXT_PAIR.search(tail)
            value, rest = (tail[: nxt.start()], tail[nxt.end():]) if nxt else (tail, "")
            roles = _label_roles(label)
            if not roles or "http" in value:
                continue
            value = re.sub(r"\(.*?\)|\[.*?\]", " ", value)
            for raw in VALUE_SPLIT.split(value):
                for name in _names(raw):
                    found += [(name, role, line_no, line.strip()[:200]) for role in roles]
    return found


def _line_of(desc: str, needle: str) -> tuple[str, str]:
    for i, line in enumerate((desc or "").splitlines(), 1):
        if needle and needle.lower() in line.lower():
            return f"mô tả dòng {i}", line.strip()[:200]
    return "mô tả", ""


def _social(desc: str) -> list[tuple[str, str]]:
    out = []
    for platform, pat in SOCIAL.items():
        for h in pat.findall(desc or ""):
            h = h.rstrip("._-/")
            if platform != "spotify":
                h = h.lower()
            out.append((platform, h))
    return out


def extract() -> None:
    seeds = {s["seed_id"]: s for s in read_seeds()}
    shows = {s["show_id"]: s for s in read_shows()}
    keys_of = {
        sid: {normalize_name(n) for n in [s["name"], s.get("youtube_channel_name", ""), *s.get("aliases", "").split(" | ")] if normalize_name(n)}
        for sid, s in seeds.items()
    }
    known_people = set().union(*keys_of.values()) | {_key(s["name"]) for s in seeds.values()}
    frozen_people = frozenset(known_people)
    known_groups = load_known_groups(seeds)
    with DOCUMENTS_PATH.open(encoding="utf-8-sig", newline="") as f:
        docs = [d for d in csv.DictReader(f) if d["document_status"] != "loại bỏ" and d.get("platform") != "web"]

    rows: list[dict] = []
    handles: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    docs_per_seed: Counter = Counter()
    for d in docs:
        title, desc, tag = d["title"], d["content"], d["content_tag"]
        ids = d["seed_ids"].split("|")
        artist_ids = [i for i in ids if i in seeds]
        show_ids = [i for i in ids if i in shows]
        artist_keys = set().union(*(keys_of[i] for i in artist_ids)) if artist_ids else set()

        def add(mention, mtype, role, song="", location="tiêu đề", quote=None, method="quy tắc: tiêu đề", group=""):
            rows.append(
                {
                    "document_id": d["document_id"], "seed_ids": d["seed_ids"], "content_tag": tag, "mention": mention, "mention_type": mtype,
                    "role": role, "song": song, "group": group, "location": location, "quote": title if quote is None else quote, "method": method,
                }
            )

        # Video show bỏ qua: "(NHÀ THIẾU NHI)" ở ATVNCG là đội thi tạm thời, không phải nhóm nhạc.
        if artist_ids and not show_ids:
            for name, group, location, quote in affiliations(title, desc, known_groups):
                add(name, "Person", "member_of", "", location, quote, "quy tắc: tên kèm nhóm trong ngoặc", group)

        songs: list[str] = []
        if show_ids:
            show = shows[show_ids[0]]
            order = show.get("title_order", "song-artist")
            first = _clean(title).split("|")[0]
            # Vài video sự kiện đảo thành "BÀI | NGHỆ SĨ": đoạn đầu không có ai đã biết mà có chữ mashup.
            if order == "artist|song" and (MASHUP_START.match(first) or not _has_name(first, known_people)):
                order = "song|artist"
            people, songs, _ = parse_title(title, order) if order != "song|artist" else _parse_song_first(title)
            # Người trong video show đã được lọc tay ở layer1_candidates; tên lạ ở đây chủ yếu là rác từ clip.
            people = [(n, r) for n, r in ((clean_person(n), r) for n, r in people) if n and (normalize_name(n) in known_people or _key(n) in known_people)]
            songs = [s for s in (clean_song(x, frozen_people) for x in songs) if s and not _has_name(s, known_people)] if people else []
            # Clip không có tên bài (Uncut, phỏng vấn, hậu trường) không phải tiết mục: không tính người tham gia.
            if not songs:
                people = []
            for name, role in people:
                for song in songs or [""]:
                    add(name, "Person", role, song)
        elif tag == "mv_audio" and artist_keys and (MUSIC_TITLE.search(title) or MUSIC_DESC.search(desc) or credit_lines(desc)):
            # Chỉ đọc tên bài khi video có dấu hiệu âm nhạc; vlog "Du Lịch Hàn Quốc - X" trên kênh nghệ sĩ thì bỏ.
            parsed = parse_artist_title(title, artist_keys, frozen_people)
            # Remix/cover nhạc ngoại trên kênh DJ Việt: không có ca sĩ đã biết và không có tiếng Việt thì ngoài phạm vi.
            if not VI_CHARS.search(title) and not any(normalize_name(n) in known_people for n in parsed["performer"] + parsed["featured"]):
                parsed = {k: [] for k in parsed}
            songs = parsed["song"]
            single = songs[0] if len(songs) == 1 else ""
            for role in ("performer", "featured", "producer"):
                for name in parsed[role]:
                    for song in songs or [""]:
                        add(name, "Person", role, song)
            for album in parsed["album"]:
                add(album, "Album", "album", single)
        for song in songs:
            add(song, "Song", "song", song)

        single_song = songs[0] if len(songs) == 1 and not COMPILATION.search(title) else ""
        if tag in {"mv_audio", "performance_show"}:
            for raw, role, line_no, line in credit_lines(desc):
                name = clean_person(raw)
                if name:
                    add(name, "Person", role, single_song, f"mô tả dòng {line_no}", line, "quy tắc: dòng credit")
            for name, role, quote in _companies(desc, artist_keys | known_people):
                location, _ = _line_of(desc, quote[:40])
                add(name, "Company", role, single_song, location, quote, "quy tắc: dòng bản quyền/label")
        for name, role, location, quote in _brands(title, desc, artist_keys):
            add(name, "Brand", role, "", location, quote, "quy tắc: brand")

        # Handle MXH chỉ tin khi video nằm trên kênh của chính một nghệ sĩ.
        if len(artist_ids) == 1 and not show_ids and d["collection_method"] != "Tìm theo tên (yt-dlp) + API":
            sid = artist_ids[0]
            docs_per_seed[sid] += 1
            for platform, h in _social(desc):
                handles[(sid, platform, h)].add(d["document_id"])

    excluded = excluded_keys()
    n_before = len(rows)
    rows = [r for r in rows if not (r["mention_type"] in {"Person", "Group"} and normalize_name(r["mention"]) in excluded)]

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    with MENTIONS_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MENTION_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    _write_handles(handles, docs_per_seed, seeds)
    print(f"Đã rút {len(rows)} mention từ {len(docs)} tài liệu → {MENTIONS_PATH} ({now_iso()})")
    print(f"  bỏ {n_before - len(rows)} mention về người trong excluded_seeds.csv")
    print("Theo loại:", dict(Counter(r["mention_type"] for r in rows)))
    print("Theo vai trò:", dict(Counter(r["role"] for r in rows).most_common()))


def _write_handles(handles: dict, docs_per_seed: Counter, seeds: dict) -> None:
    counts: dict[tuple[str, str], list[int]] = defaultdict(list)
    seeds_per_handle: Counter = Counter()
    for (sid, platform, h), doc_ids in handles.items():
        counts[(sid, platform)].append(len(doc_ids))
        seeds_per_handle[(platform, h)] += 1
    out = []
    for (sid, platform, h), doc_ids in sorted(handles.items(), key=lambda x: (x[0][0], x[0][1], -len(x[1]))):
        n = len(doc_ids)
        share = n / docs_per_seed[sid] if docs_per_seed[sid] else 0
        top = counts[(sid, platform)]
        if seeds_per_handle[(platform, h)] >= 3:
            suggest = "xem lại: trang chung của nhiều nghệ sĩ (label/đội nhóm)"
        elif n == max(top) and top.count(n) > 1:
            suggest = "xem lại: nhiều handle ngang nhau"
        # Link xuất hiện nhiều nhất và đều đặn trong mô tả kênh chính thức mới được gợi ý là tài khoản của nghệ sĩ.
        elif n == max(top) and n >= 3 and share >= 0.2:
            suggest = "nhận"
        else:
            suggest = "xem lại"
        out.append(
            {
                "handle_key": f"{sid}|{platform}|{h}", "seed_id": sid, "name": seeds[sid]["name"], "platform": platform, "handle": h, "url": SOCIAL_URL[platform].format(h),
                "n_videos": n, "share": round(share, 2), "n_artists_using": seeds_per_handle[(platform, h)], "suggest": suggest,
                "example_document": sorted(doc_ids)[0], "approve": "", "review_note": "",
            }
        )
    _write_preserving_review(HANDLES_PATH, out, "handle_key")
    accepted = Counter(r["platform"] for r in out if r["suggest"] == "nhận")
    print(f"Handle MXH: {len(out)} dòng → {HANDLES_PATH}; gợi ý nhận theo nền tảng: {dict(accepted)}")
