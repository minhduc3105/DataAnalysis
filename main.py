import argparse
import sys
from collections import Counter

from dotenv import load_dotenv

from crawler import documents, extract, graph, layer1_extract, layer2, shows, spotify, viewer, youtube, youtube_search
from crawler.common import iter_jsonl, read_seeds, select_seeds, write_seeds
from crawler.config import PERIOD_END, PERIOD_START, RAW_DIR

ARTIST_TYPES = {"Person", "Group"}
ALL_TYPES = {"Person", "Group", "Company", "Show"}


def cmd_seeds(_args) -> None:
    seeds = read_seeds()
    print(f"{len(seeds)} seed")
    print("Theo loại:", dict(Counter(s["entity_type"] for s in seeds)))
    print("Theo nhóm nhạc:", dict(Counter(s["genre_group"] for s in seeds)))
    print("Có kênh YouTube:", sum(bool(s["youtube_channel_id"]) for s in seeds))
    print("Có Spotify ID:", sum(bool(s["spotify_artist_id"]) for s in seeds))
    dup = [n for n, c in Counter(s["seed_id"] for s in seeds).items() if c > 1]
    if dup:
        print("TRÙNG seed_id:", dup)


def cmd_youtube(args) -> None:
    seeds = read_seeds()
    if youtube.normalize_manual_channels(seeds):
        write_seeds(seeds)
        print("Đã đổi link/@handle sửa tay trong seeds.csv thành channel ID")
    chosen = select_seeds(seeds, args.seed, ALL_TYPES)
    if args.action == "resolve":
        if not args.force:
            chosen = [s for s in chosen if not s["youtube_channel_id"] and s.get("youtube_verified") != youtube.NOT_FOUND]
        print(f"Dò kênh cho {len(chosen)} seed (lưu seeds.csv sau mỗi 10 người; dừng giữa chừng thì chạy lại sẽ tiếp tục)")
        youtube.resolve(chosen, checkpoint=lambda: write_seeds(seeds))
        found = sum(bool(s["youtube_channel_id"]) for s in chosen)
        print(f"Đã dò {len(chosen)} seed: tìm được {found}, không tìm được {len(chosen) - found}; xem data/interim/youtube_channel_candidates.csv")
    elif args.action == "search-people":
        youtube_search.run(args.seed, args.max_results, args.force, only_missing=not args.all)
    else:
        youtube.crawl(chosen, args.backend, args.max_videos)


def cmd_spotify(args) -> None:
    seeds = read_seeds()
    chosen = select_seeds(seeds, args.seed, ARTIST_TYPES)
    client = spotify.SpotifyClient.from_env()
    if args.action == "resolve":
        if not args.force:
            chosen = [s for s in chosen if not s["spotify_artist_id"]]
        spotify.resolve(client, chosen)
        write_seeds(seeds)
        print(f"Đã dò {len(chosen)} seed; xem data/interim/spotify_artist_candidates.csv")
    else:
        spotify.crawl(client, chosen)


def cmd_shows(args) -> None:
    shows.crawl(args.show)


def cmd_layer1(_args) -> None:
    layer1_extract.extract()


def cmd_layer2(args) -> None:
    layer2.promote(args.suggested)


def cmd_documents(_args) -> None:
    documents.build(read_seeds())


def cmd_extract(_args) -> None:
    extract.extract()


def cmd_graph(_args) -> None:
    graph.build()


def cmd_view(_args) -> None:
    viewer.build()


def cmd_stats(_args) -> None:
    yt = list(iter_jsonl((RAW_DIR / "youtube").glob("*.jsonl")))
    print(f"Giai đoạn: {PERIOD_START} → {PERIOD_END}")
    print(f"YouTube: {len(yt)} video thô, theo giai đoạn: {dict(Counter(r.get('period_status') for r in yt))}")
    print(f"  Lọc ở tầng 1: {dict(Counter(r['crawl_skip_reason'] for r in yt if r.get('crawl_skip_reason')))}")
    albums = list(iter_jsonl((RAW_DIR / "spotify" / "albums").glob("*.jsonl")))
    artist_ids, track_ids, labels = set(), set(), set()
    for a in albums:
        labels.add((a.get("label") or "").strip())
        for t in a.get("tracks", []):
            track_ids.add(t["id"])
            artist_ids.update(x["id"] for x in t.get("artists", []))
        artist_ids.update(x["id"] for x in a.get("artists", []))
    labels.discard("")
    print(f"Spotify: {len({a['album_id'] for a in albums})} release, {len(track_ids)} track, {len(artist_ids)} nghệ sĩ, {len(labels)} label")
    print("(Số sơ bộ theo ID nền tảng, chưa gộp trùng thực thể.)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    load_dotenv()
    p = argparse.ArgumentParser(description="Thu thập dữ liệu YouTube/Spotify cho mạng lưới âm nhạc Việt Nam")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seeds", help="Thống kê seeds.csv").set_defaults(func=cmd_seeds)

    yt = sub.add_parser("youtube", help="Dò kênh hoặc thu thập video")
    yt.add_argument("action", choices=["resolve", "crawl", "search-people"])
    yt.add_argument("--max-results", type=int, default=25, help="search-people: số kết quả tìm kiếm xét cho mỗi người")
    yt.add_argument("--all", action="store_true", help="search-people: tìm cho cả người đã có kênh")
    yt.add_argument("--seed", nargs="*", help="Chỉ chạy các seed_id này")
    yt.add_argument("--backend", choices=["auto", "api", "ytdlp"], default="auto")
    yt.add_argument("--max-videos", type=int, default=600)
    yt.add_argument("--force", action="store_true", help="Dò lại cả seed đã có kênh")
    yt.set_defaults(func=cmd_youtube)

    sp = sub.add_parser("spotify", help="Dò artist ID hoặc thu thập release")
    sp.add_argument("action", choices=["resolve", "crawl"])
    sp.add_argument("--seed", nargs="*")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_spotify)

    sh = sub.add_parser("shows", help="Tầng 0: tải video từ playlist trong seeds/shows.csv")
    sh.add_argument("action", choices=["crawl"])
    sh.add_argument("--show", nargs="*", help="Chỉ chạy các show_id này")
    sh.set_defaults(func=cmd_shows)

    l1 = sub.add_parser("layer1", help="Tầng 1: rút ứng viên nghệ sĩ từ video chương trình")
    l1.add_argument("action", choices=["extract"])
    l1.set_defaults(func=cmd_layer1)

    l2 = sub.add_parser("layer2", help="Tầng 2: chuyển ứng viên đã duyệt thành seeds.csv để crawl")
    l2.add_argument("action", choices=["promote"])
    l2.add_argument("--suggested", action="store_true", help="Lấy cả dòng suggest=nhận chưa duyệt (trừ dòng approve=n)")
    l2.set_defaults(func=cmd_layer2)

    sub.add_parser("documents", help="Xuất bảng Document").set_defaults(func=cmd_documents)
    sub.add_parser("extract", help="Rút credit, bài hát, label, brand, handle MXH từ documents.csv").set_defaults(func=cmd_extract)
    sub.add_parser("graph", help="Dựng bảng Entity/Relation/Evidence từ mentions.csv").set_defaults(func=cmd_graph)
    sub.add_parser("view", help="Tạo trang HTML xem graph (data/interim/graph/viewer.html)").set_defaults(func=cmd_view)
    sub.add_parser("stats", help="Thống kê dữ liệu đã thu").set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
