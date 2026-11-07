import csv
import shutil

from .common import normalize_name, read_seeds, today_iso, write_seeds
from .config import SEEDS_PATH
from .layer1 import CANDIDATES_PATH, _key
from .youtube import blocked_channels

BACKUP_PATH = SEEDS_PATH.with_name("seeds_v1_memory.csv")
EXTRA_PATH = SEEDS_PATH.with_name("extra_seeds.csv")
EXCLUDED_PATH = SEEDS_PATH.with_name("excluded_seeds.csv")
ALIASES_PATH = SEEDS_PATH.with_name("aliases.csv")
YES = {"y", "yes", "có", "co", "x", "1", "ok"}
NO = {"n", "no", "không", "khong", "0"}


def _selected(row: dict, include_suggested: bool) -> bool:
    approve = (row.get("approve") or "").strip().lower()
    if approve in YES:
        return True
    if approve in NO:
        return False
    return include_suggested and row.get("suggest") == "nhận"


def load_aliases() -> dict[str, tuple[str, set[str]]]:
    """Trả {khóa tên bất kỳ: (khóa tên chuẩn, các tên gọi khác)}."""
    if not ALIASES_PATH.exists():
        return {}
    groups: dict[str, set[str]] = {}
    with ALIASES_PATH.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            groups.setdefault(r["canonical_name"].strip(), set()).add(r["alias"].strip())
    out = {}
    for canonical, alias_names in groups.items():
        for name in {canonical} | alias_names:
            out[_key(name)] = (_key(canonical), alias_names)
    return out


def _canonical(name: str, aliases: dict) -> str:
    key = _key(name)
    return aliases.get(key, (key, set()))[0]


def promote(include_suggested: bool) -> None:
    with CANDIDATES_PATH.open(encoding="utf-8-sig", newline="") as f:
        candidates = [r for r in csv.DictReader(f) if _selected(r, include_suggested)]
    aliases = load_aliases()
    blocked = blocked_channels()

    old_seeds = read_seeds()
    if not BACKUP_PATH.exists():
        shutil.copyfile(SEEDS_PATH, BACKUP_PATH)
    backup = {s["seed_id"]: s for s in read_seeds(BACKUP_PATH)}
    by_source = {s.get("source_key"): s for s in old_seeds if s.get("source_key")}
    by_name = {_canonical(s["name"], aliases): s for s in list(backup.values()) + old_seeds if s.get("entity_type") in {"Person", "Group"}}

    used_ids = {s["seed_id"] for s in old_seeds} | set(backup)
    next_num = 1 + max((int(i.split("_")[1]) for i in used_ids if i.startswith("ART_")), default=0)

    seeds: list[dict] = []
    seen_keys: dict[str, dict] = {}
    seen_channels: dict[str, dict] = {}

    excluded_keys: set[str] = set()
    if EXCLUDED_PATH.exists():
        with EXCLUDED_PATH.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                excluded_keys |= {k for k in (r.get("source_key"), _canonical(r.get("name", ""), aliases), r.get("seed_id")) if k}
    n_excluded = 0

    def add(seed: dict, key: str) -> bool:
        nonlocal n_excluded
        if key in excluded_keys or seed.get("source_key") in excluded_keys or seed["seed_id"] in excluded_keys:
            n_excluded += 1
            return False
        channel = seed.get("youtube_channel_id")
        if key in seen_keys or (channel and channel in seen_channels):
            dup = seen_keys.get(key) or seen_channels.get(channel)
            if dup is not None and seed["name"] != dup["name"]:
                names = {a for a in dup.get("aliases", "").split(" | ") if a}
                dup["aliases"] = " | ".join(sorted(names | {seed["name"]}))
            return False
        seen_keys[key] = seed
        if channel:
            seen_channels[channel] = seed
        seeds.append(seed)
        return True

    for c in candidates:
        key = _canonical(c["name"], aliases)
        prev = by_source.get(c["candidate_key"]) or (backup.get(c["in_old_seeds"]) if c.get("in_old_seeds") else None) or by_name.get(key)
        if prev and prev["seed_id"].startswith(("SEED_", "ART_")):
            seed_id = prev["seed_id"]
        else:
            seed_id = f"ART_{next_num:04d}"
            next_num += 1
        prev = prev or {}
        # Kênh đã có trong seeds (kể cả do người dùng sửa tay) được ưu tiên hơn kênh rút từ @handle.
        channel = prev.get("youtube_channel_id", "") or c.get("youtube_channel_id", "")
        if channel in blocked:
            channel = ""
        alias_names = aliases.get(key, ("", set()))[1] | {n for n in c.get("name_variants", "").split(" | ") if n and n != c["name"]}
        add(
            {
                "seed_id": seed_id,
                # Tên người dùng đã sửa trong seeds.csv được giữ, không lấy lại tên thô từ candidate.
                "name": prev.get("name") or c["name"],
                "entity_type": c.get("entity_type") or "Person",
                "genre_group": prev.get("genre_group", ""),
                "youtube_channel_id": channel,
                "youtube_channel_name": prev.get("youtube_channel_name", "") if channel == prev.get("youtube_channel_id") else c.get("youtube_handle", ""),
                "youtube_verified": prev.get("youtube_verified", "") if channel == prev.get("youtube_channel_id") else ("không rõ" if channel else ""),
                "spotify_artist_id": prev.get("spotify_artist_id", ""),
                "spotify_name": prev.get("spotify_name", ""),
                "verification_status": "đã duyệt" if (c.get("approve") or "").strip().lower() in YES else "gợi ý tự động – chờ duyệt",
                "checked_at": prev.get("checked_at", "") or today_iso(),
                "notes": f"vai trò tầng 1: {c.get('roles', '')}",
                "layer": "1",
                "source_key": c["candidate_key"],
                "discovered_in": c.get("shows", ""),
                "aliases": " | ".join(sorted(alias_names - {c["name"]})),
            },
            key,
        )
    from_layer1 = len(seeds)

    skipped_extra = []
    current_by_id = {s["seed_id"]: s for s in old_seeds}
    if EXTRA_PATH.exists():
        for s in read_seeds(EXTRA_PATH):
            # Bản trong seeds.csv có thể đã được người dùng sửa (tên, kênh), nên ưu tiên nó.
            s = {**s, **current_by_id.get(s["seed_id"], {})}
            if s.get("youtube_channel_id") in blocked:
                s["youtube_channel_id"] = ""
            key = _canonical(s["name"], aliases)
            if not add({**s, "layer": s.get("layer") or "1b"}, key):
                skipped_extra.append(s["name"])

    write_seeds(seeds)
    have_yt = sum(bool(s["youtube_channel_id"]) for s in seeds)
    have_sp = sum(bool(s["spotify_artist_id"]) for s in seeds)
    print(f"seeds.csv mới: {len(seeds)} người/nhóm (tầng 1: {from_layer1}, bổ sung theo dòng nhạc: {len(seeds) - from_layer1}); bản cũ ở {BACKUP_PATH.name}")
    if skipped_extra:
        print(f"  bỏ qua vì trùng với tầng 1 hoặc nằm trong excluded_seeds.csv: {', '.join(skipped_extra)}")
    print(f"  loại theo excluded_seeds.csv: {n_excluded}")
    print(f"  đã có kênh YouTube: {have_yt} | cần dò: {len(seeds) - have_yt} | đã có Spotify ID: {have_sp}")
