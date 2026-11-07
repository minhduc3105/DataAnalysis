import re

from .common import normalize_name

SHORT_MAX_SECONDS = 60
SHORT_REASON = "video ngắn/Shorts"
ARTIST_TYPES = {"Person", "Group"}

VI_CHARS = re.compile(r"[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.IGNORECASE)


def _words(*patterns: str) -> re.Pattern:
    return re.compile(r"(?<!\w)(?:" + "|".join(patterns) + r")(?!\w)", re.IGNORECASE)


BRAND = _words("tvc", "(?<!không )(?<!no )quảng cáo", "đại sứ", "ambassador", "brand", "nhãn hàng", "tài trợ", "campaign", "sponsored", "collab")
NON_MUSIC = _words(
    "vlog", "behind the scenes?", "bts", "unbox(?:ing)?", "phỏng vấn", "interview", "reaction", "hậu trường", "podcast", "q&a", "mukbang",
    "best cut", "short film", "phim ngắn", "web ?drama", "trailer phim", "talkshow", "startalk", "livestream", "gameshow", "minigame",
)
PERFORMANCE = _words(
    "live", "stage", "performance", "sân khấu", "concert", "tour", "festival", "lễ hội", "biểu diễn", "showcase",
    "fancam", "công diễn", "chung kết", "bán kết", "vòng loại", r"tập \d+", r"episode \d+", "đêm nhạc", "liveshow",
    "live ?band", "live session", "unplugged", "in the moment", "đại nhạc hội", "countdown", "gala", "mini ?show",
)
MUSIC = _words(
    "mv", "m/v", "music video", "official", "lyrics?", "audio", "visualizer", r"ft\.?", r"feat\.?", r"prod\.?",
    "ost", "album", "ep", "single", "remix", "acoustic", "cover", "teaser", "track", "bài hát", "ca khúc",
    "liên khúc", "lk", "mashup", "medley", "nhạc xuân", "nhạc tết", "playlist", "special clip", "lyric video", "dance practice",
)
SONG_TITLE = re.compile(r"\S.*\s[-–—|]\s\S")
CREDIT = re.compile(r"sáng tác|composer|songwriter|lyricist|producer|nhạc sĩ|hòa âm|phối khí|phát hành bởi|℗", re.IGNORECASE)
MINOR_VERSION = re.compile(r"karaoke|instrumental|\(beat\)|\[beat\]|beat gốc|beat chuẩn|tone nam|tone nữ", re.IGNORECASE)
SHORTS_TAG = re.compile(r"#shorts?\b", re.IGNORECASE)


def iso_duration_seconds(value) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _show_name_keys(name: str) -> set[str]:
    keys = set()
    for part in [name, *name.split(" - ")]:
        key = normalize_name(part)
        if len(key) > 3:
            keys |= {key, key.replace(" ", "")}
    return keys


class Scope:
    def __init__(self, seeds: list[dict]):
        from .shows import read_shows

        self.seed_type = {s["seed_id"]: s["entity_type"] for s in seeds}
        artists = [s["name"] for s in seeds if s["entity_type"] in ARTIST_TYPES]
        # Tên một chữ (Ngắn, Min, Orange…) dễ trùng từ thường khi bỏ dấu, nên phải khớp nguyên dạng.
        self.artist_names = {normalize_name(n) for n in artists if len(normalize_name(n).split()) > 1}
        single = [re.escape(n) for n in artists if len(normalize_name(n).split()) == 1]
        self.exact_artist = re.compile(r"(?<!\w)(?:" + "|".join(single) + r")(?!\w)") if single else None
        self.show_names = {k for s in seeds if s["entity_type"] == "Show" for k in _show_name_keys(s["name"])}
        self.show_names |= {k for s in read_shows() for k in _show_name_keys(s["show_name"])}
        self.artist_names.discard("")
        self.show_names.discard("")

    @staticmethod
    def _contains(names: set[str], text: str) -> bool:
        padded = f" {normalize_name(text)} "
        return any(f" {n} " in padded for n in names)

    def _mentions_artist(self, text: str) -> bool:
        if self._contains(self.artist_names, text):
            return True
        return bool(self.exact_artist and self.exact_artist.search(text or ""))

    @staticmethod
    def is_short(title: str, duration) -> bool:
        seconds = iso_duration_seconds(duration)
        return bool(SHORTS_TAG.search(title or "")) or (seconds is not None and seconds <= SHORT_MAX_SECONDS)

    def crawl_skip_reason(self, seed_id: str, title: str, duration, category) -> str | None:
        """Tầng 1: chỉ bỏ thứ chắc chắn vô dụng; trả None nếu giữ."""
        title = title or ""
        if self.is_short(title, duration):
            return SHORT_REASON
        if self.seed_type.get(seed_id) in ARTIST_TYPES:
            return None
        if category in {"10", "Music"}:
            return None
        if MUSIC.search(title) or PERFORMANCE.search(title) or BRAND.search(title):
            return None
        if self._contains(self.show_names, title) or self._mentions_artist(title):
            return None
        return "kênh công ty/chương trình: không phải nội dung âm nhạc"

    def classify(self, seed_ids: set[str], title: str, description: str) -> tuple[str, str]:
        """Tầng 2: trả (content_tag, exclude_reason); exclude_reason rỗng nghĩa là giữ."""
        title = title or ""
        description = description or ""
        from_artist_channel = any(self.seed_type.get(s) in ARTIST_TYPES for s in seed_ids)
        from_show_playlist = any(s.startswith("SHOW_") for s in seed_ids)

        if MINOR_VERSION.search(title):
            return "other", "phiên bản phụ: karaoke/beat"
        if not description.strip():
            return "other", "không có nội dung để trích xuất"
        if not from_artist_channel and not VI_CHARS.search(title) and not self._mentions_artist(title):
            return "other", "ngoài phạm vi: không phải nhạc Việt"

        if BRAND.search(title):
            return "brand", ""
        if NON_MUSIC.search(title):
            return "other", ""
        if from_show_playlist or PERFORMANCE.search(title) or self._contains(self.show_names, title):
            return "performance_show", ""
        if MUSIC.search(title) or CREDIT.search(description):
            return "mv_audio", ""
        # Kênh nghệ sĩ hay đặt tiêu đề "Tên bài - Nghệ sĩ" mà không kèm chữ MV/Official.
        if from_artist_channel and SONG_TITLE.search(title) and self._mentions_artist(title):
            return "mv_audio", ""
        return "other", ""
