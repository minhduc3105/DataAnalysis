# Mạng lưới Ca sĩ – Nhạc sĩ – Công ty giải trí Việt Nam

Đề tài 23, xem [Plan.md](Plan.md). Giai đoạn dữ liệu: 01/01/2016 – 21/10/2026.

## Cài đặt

```powershell
uv sync
copy .env.example .env   # điền key, không commit .env
```

## Chiến lược nhiều tầng (bắt đầu từ chương trình)

```powershell
uv run python main.py shows crawl        # Tầng 0: tải video trong playlist của seeds/shows.csv
uv run python main.py layer1 extract     # Tầng 1: sinh ứng viên người, bài hát, công ty/nhãn hàng
```

| File (data/interim) | Nội dung | Người duyệt điền |
|---|---|---|
| `layer1_candidates.csv` | Person/Group: tên, vai trò (performer, coach, composer, producer), số video/chương trình, kênh YouTube nếu có | `approve` = y/n, sửa `entity_type` thành Group nếu là nhóm |
| `layer1_songs.csv` | Song: tên bài, người trình bày, nhạc sĩ/producer (nếu có credit), có nằm trong mashup | `approve`, `review_note` |
| `layer1_orgs.csv` | Company/Brand: chủ sở hữu chương trình, hãng phát hành audio (lnk.to), đơn vị format, nhà tài trợ, kèm câu bằng chứng | `approve`, sửa `entity_type` nếu sai |

`seeds/shows.csv` có cột `title_order` cho biết cách đọc tiêu đề: `song-artist` (mặc định), `artist-song`, `artist|song`, `free` (lấy người từ dòng credit), `mascot` (tên linh vật, bỏ qua). Tên không phải nghệ sĩ thì thêm vào `seeds/layer1_blocklist.txt`. Chạy lại `layer1 extract` không làm mất cột đã duyệt.

## Quy trình thu thập (YouTube, Spotify)

```powershell
uv run python main.py seeds                     # thống kê seeds/seeds.csv
uv run python main.py youtube resolve           # dò kênh chính thức (tick xanh + khớp tên) → điền seeds.csv
uv run python main.py youtube crawl             # tự dùng API nếu có YOUTUBE_API_KEY, nếu không dùng yt-dlp
uv run python main.py spotify resolve           # dò artist ID (chỉ tự điền khi trùng tên duy nhất)
uv run python main.py spotify crawl             # liệt kê mọi release trong giai đoạn; lấy chi tiết (track, ℗/©) cho 5 release nổi bật (--top N, 0 = tất cả)
uv run python main.py documents                 # xuất data/interim/documents.csv (bảng Document)
uv run python main.py web sources-check         # kiểm tra RSS và website nguồn
uv run python main.py web discover              # tìm URL từ RSS, sitemap và Google News RSS
uv run python main.py web discover --from 2024-01-01 --to 2024-12-31  # giới hạn theo ngày đăng
uv run python main.py web crawl                 # tải tiếp URL đã tìm, giữ HTML gốc để chạy lại
uv run python main.py web clean                 # xuất web_documents.csv và document_entities.csv
uv run python main.py web signals               # phát hiện cặp người có tín hiệu hợp tác/xung đột
uv run python main.py extract                   # rút credit, bài hát, album, label, brand, handle MXH → mentions.csv, social_handles.csv
uv run python main.py graph                     # dựng bảng Entity/Relation/Evidence → data/interim/graph/
uv run python main.py stats
```

## Neo4j và phân tích mạng (Bước 11–12)

Cần Neo4j Desktop, một database đang chạy có plugin **Graph Data Science**, và `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` trong `.env`.

```powershell
uv run python main.py neo4j load     # xóa database, nạp Entity/Relation/Document/Evidence, in kết quả kiểm tra Bước 11
uv run python main.py analyze        # chạy GDS: WCC, Louvain, PageRank, Betweenness, Degree → data/interim/analysis/
```

- Nút: `:Entity:<Loại>` (Person, Song…), thêm `:Document` và `:Evidence` để truy nguồn; hai loại này và cạnh `FROM_DOCUMENT` không tính vào chỉ tiêu.
- Cạnh mang `relation_id`; bằng chứng tìm bằng `MATCH (e:Evidence {relation_id: r.relation_id})`.
- Mạng hợp tác: nút Person/Group, cạnh COLLABORATED_WITH vô hướng, `weight` = số bài khác nhau cùng trình bày. Chạy 2 bản: có và không có cạnh chỉ đến từ tiết mục chương trình (`show_only`), để kiểm tra độ ổn định.
- Thời gian (RQ3) dùng `first_year` = năm đăng sớm nhất của tài liệu bằng chứng; với YouTube đây là xấp xỉ năm phát hành.
- `analysis/gephi_nodes.csv`, `gephi_edges.csv`: mở trong Gephi (File → Import Spreadsheet) để vẽ cộng đồng. Truy vấn demo cho Neo4j Browser ở [neo4j/queries.cypher](neo4j/queries.cypher).

Chạy lại `documents → extract → graph` mỗi khi sửa seeds hoặc crawl thêm. ID trong `graph/` (PER_, SON_, REL_…) được giữ cố định qua `graph/id_registry.csv`.

Luồng web đọc danh mục `seeds/web_sources.csv`, lấy thực thể từ `data/interim/graph/entities.csv`, lưu hàng đợi và checkpoint tìm kiếm tại `data/raw/web/crawl.sqlite3`, HTML/nội dung tại `data/raw/web/`. `discover` lấy URL từ RSS, sitemap (khi chạy toàn kỳ) và Google News RSS với một query cho mỗi entity trên toàn khoảng ngày; query được chạy tiếp theo từng đợt, mặc định tối đa 50 query mỗi lượt. Dùng `--search-limit` để đổi giới hạn, `--entity` để lọc ID. Thêm `--from YYYY-MM-DD` và/hoặc `--to YYYY-MM-DD` để giới hạn kỳ tìm kiếm; URL vẫn được lưu dù ngày RSS ngoài kỳ, rồi ngày xuất bản bài gốc được xác minh lúc crawl/clean. Chạy `discover --dry-run` để xem query dự kiến mà không gọi mạng hoặc ghi checkpoint. Mỗi URL nguyên bản được lưu, chỉ chuỗi giống hệt mới trùng; query, nguồn và entity phát hiện link vẫn được lưu trong provenance. `crawl` giải URL Google News, tải trang và giữ riêng URL đầu vào, URL giải được và URL cuối sau redirect. `clean` xác minh loại trang, ngày và liên quan cho tập phân tích kỳ **01/01/2016–21/10/2026**.

`web crawl` tự giải tối đa 50 URL Google News mỗi lượt ra URL bài gốc, rồi tải URL HTTP(S) đang chờ; dùng `--resolve-limit` để đổi số link giải, `--limit` để giới hạn số URL và `--workers` để đặt số tải song song (mặc định 8). Các request tới cùng host được giãn nhịp. Kết quả được ghi theo lô; dừng giữa lượt thì các lô đã lưu vẫn nằm trong DB/CSV. URL không phải bài, ảnh, chuyên mục, thiếu ngày, ngày mâu thuẫn hoặc chưa rõ liên quan vẫn được giữ trong kho và gắn lý do để duyệt. Wikipedia/Wikidata được đánh dấu ngoài phạm vi và không tải nội dung. Nội dung giống nhau được đánh dấu bằng `duplicate_content_of`, không xóa URL. Bài ngoài kỳ vẫn được lưu nhưng không vào tập phân tích. URL RSS/sitemap và query giữ nguồn gốc; thời gian RSS không thay ngày bài gốc. `web crawl --entity PER_0001` lọc URL đang chờ theo entity. Số trang tải, đạt, chờ duyệt, ngoài kỳ và lỗi được ghi riêng ở `web_crawl_report.json`.

`web clean` dùng pandas để đọc bảng, chuẩn hóa ngày và văn bản, phân loại phạm vi, nối ID thực thể và tạo thống kê; không gộp URL khác nhau hoặc tài liệu chỉ vì nội dung giống nhau. `web signals` xuất `web_relation_candidates.csv` với câu trích, loại tín hiệu, trạng thái quan hệ hiện tại trong graph và trạng thái duyệt. Sửa `review_status`/`query_status` trong CSV để duyệt; lần chạy sau giữ quyết định đó, và đánh dấu duyệt lại nếu nội dung đổi. Từ điển chỉnh được ở `seeds/web_relation_terms.csv`; quan hệ có sẵn không chặn tìm tín hiệu loại khác. Google News candidates nằm ở `web_candidates.csv`; điền URL gốc rồi chạy `web review-import`. Query đã hoàn tất theo bộ lọc cũ sẽ được chạy lại một lượt khi phiên bản bộ lọc đổi. Dùng `web recover-urls --dry-run` để đếm URL lịch sử bị loại có thể phục hồi, rồi `web recover-urls` để đưa chúng về hàng đợi. Báo cáo query nằm ở `web_search_report.json`.

## Rút thực thể và quan hệ ([crawler/extract.py](crawler/extract.py), [crawler/graph.py](crawler/graph.py))

| Nguồn trong video | Rút ra | Quan hệ |
|---|---|---|
| Tiêu đề kênh nghệ sĩ `NGHỆ SĨ - BÀI (ft. X) (prod. Y) \| Album Z` | Person, Song, Album | PERFORMED, FEATURED_ON, PRODUCED, TRACK_OF, COLLABORATED_WITH (suy ra) |
| Dòng credit `Sáng tác:`, `Composer:`, `Producer:`, `Hòa âm phối khí:`, `Trình bày:` | Person | COMPOSED, PRODUCED, PERFORMED |
| Dòng `℗`, `Label:`, link `wmvn/umvn/smevn.lnk.to`, `© … Entertainment/Records` | Company | RELEASED_BY |
| Tiêu đề video playlist show/sự kiện | Person, Song, Show/Event | CONTESTANT_ON (show thi đấu), PERFORMED_AT, JUDGE_ON (Team X) |
| `© … thuộc về`, `sản xuất bởi`, `phân phối bởi` trên video show | Company | ORGANIZED_BY |
| `đại sứ thương hiệu`, `TVC X`, `(X Campaign)` | Brand | AMBASSADOR_OF |
| `Tên (Nhóm)` khi Nhóm là Group đã biết (seeds hoặc `entity_overrides.csv`); tiền tố crew `HUSTLANG X`, `RPT X` | Person, Group | MEMBER_OF |
| Link instagram/facebook/tiktok/spotify trong mô tả kênh nghệ sĩ | `social_handles.csv` | đầu vào crawl TikTok/IG/FB |

- Người trong video show chỉ giữ khi đã có trong seeds (danh sách đã lọc tay); người trong `excluded_seeds.csv` bị bỏ khỏi mọi mention.
- Video gộp nhiều bài (liên khúc, playlist, tuyển tập) không gán credit cho bài nào.
- `©` ghi chính nghệ sĩ/kênh là chủ sở hữu không tạo Company; MCN (Network) không tạo RELEASED_BY.
- Mọi quan hệ và bằng chứng ở trạng thái `chờ kiểm tra`; thực thể ngoài seeds là `chưa xác minh`.
- Sửa tay khi duyệt (chạy lại `graph` là áp dụng):
  - `seeds/entity_blocklist.csv` (`entity_type,name,reason`): tên rút sai, không tạo node nữa.
  - `seeds/company_aliases.csv` (`canonical_name,alias,note`): gộp các cách viết của cùng công ty, hiển thị theo `canonical_name`.
  - `seeds/aliases.csv`: gộp các tên gọi của cùng nghệ sĩ.
  - `seeds/entity_overrides.csv` (`name,entity_type,canonical_name,note`): tên rút được thực ra là `Brand`, `Company`, `Group` hoặc `drop` (rác). Brand chỉ nhận khi đứng trong tiêu đề ("X x CLOSEUP") và tạo cạnh AMBASSADOR_OF cho nghệ sĩ của video.
  - `seeds/show_roles.csv` (`show_name,person,role,note`): HLV/giám khảo; chỉ dùng để không ghi họ là thí sinh, không tạo cạnh.
- Lọc tự động khi dựng graph: nhạc sĩ nước ngoài của bài cover (giữ người hợp tác trực tiếp với nghệ sĩ Việt), cụm từ/tên bài bị nhận là người, họ đứng một mình, từ thường một chữ; danh sách "Thể hiện:" quá 6 người không suy ra COLLABORATED_WITH.

Thêm `--seed SEED_001 SEED_002` để chạy một phần. Lệnh crawl chạy tiếp được sau khi bị ngắt (bỏ qua mục đã có).

## Dữ liệu

| Đường dẫn | Nội dung |
|---|---|
| `seeds/seeds.csv` | Danh sách khởi tạo; cột `verification_status` do người duyệt cập nhật |
| `data/interim/*_candidates.csv` | Kênh/artist ứng viên để duyệt tay |
| `data/raw/youtube/<channel_id>.jsonl` | Video thô (không commit) |
| `data/raw/spotify/releases/<artist_id>.jsonl` | Mọi release trong giai đoạn (tên, ngày, nghệ sĩ của release, hạng top-tracks, lượt xem MV YouTube cùng tên) |
| `data/raw/spotify/albums/<artist_id>.jsonl` | Chi tiết release nổi bật kèm track và dòng ℗/© (không commit) |
| `data/interim/documents.csv` | Bảng `Document` theo Bước 2 của Plan.md |
| `data/interim/web_documents.csv`, `document_entities.csv` | Bài báo/website và các liên kết thực thể ứng viên để duyệt |
| `data/interim/web_relation_candidates.csv`, `web_search_report.json`, `web_crawl_report.json` | Tín hiệu quan hệ, hàng đợi query và thống kê crawl theo trạng thái |
| `data/interim/mentions.csv` | Mọi tên rút được kèm vai trò, câu trích và vị trí |
| `data/interim/social_handles.csv` | Handle MXH theo nghệ sĩ; cột `suggest`, điền `approve` để duyệt |
| `data/interim/graph/entities.csv`, `relations.csv`, `evidence.csv` | Bảng `Entity`, `Relation`, `Evidence` theo Bước 2.3 Plan.md |
| `logs/crawl_runs.csv` | Nhật ký từng lượt chạy, gồm lỗi và nguồn thất bại |

## Bảng `Document` (`data/interim/documents.csv`)

Gồm đủ 13 trường của bảng Document ở Bước 2.3 Plan.md, thêm 3 cột phụ `platform`, `platform_item_id`, `seed_ids`.

- `content` của YouTube là mô tả video gốc.
- `content` của Spotify là **văn bản ghép từ dữ liệu API** (nghệ sĩ, ngày phát hành, dòng ℗/©, danh sách bài), không phải văn bản gốc; khi báo cáo cần ghi rõ đây là dữ liệu có cấu trúc.
- `document_status` mặc định `cần kiểm tra`; chỉ Bước 5 (lọc phạm vi, chống trùng) mới đổi sang `hợp lệ`, `trùng lặp` hoặc `loại bỏ` kèm `exclude_reason`.
- Từ 02/2026 Spotify bỏ trường `label` với app Development Mode; công ty phát hành lấy từ dòng ℗/© trong `copyrights`.

## Lọc phạm vi 2 tầng ([crawler/scope.py](crawler/scope.py))

**Tầng 1 – khi crawl YouTube:** chỉ lưu ID và lý do (`crawl_skip_reason`), không lưu nội dung.

- Video ≤ 60 giây hoặc có `#shorts`.
- Kênh công ty/chương trình: bỏ video không thuộc danh mục Âm nhạc **và** tiêu đề không có từ khóa âm nhạc, biểu diễn, thương hiệu, tên show hay tên nghệ sĩ seed. Kênh của nghệ sĩ/nhóm không bị lọc ở tầng này.

**Tầng 2 – khi xuất `documents.csv`:** gắn `content_tag`; chỉ 3 trường hợp bị `loại bỏ` kèm `exclude_reason`.

| `content_tag` | Dấu hiệu chính |
|---|---|
| `mv_audio` | MV, Official, Lyric, Audio, ft., hoặc mô tả có credit sáng tác/producer |
| `performance_show` | Live, Stage, sân khấu, concert, tour, công diễn, tên show |
| `brand` | TVC, quảng cáo, đại sứ, collab nhãn hàng |
| `release` | Release Spotify |
| `other` | Vlog, phỏng vấn, hậu trường và phần còn lại |

| `exclude_reason` | Điều kiện |
|---|---|
| `phiên bản phụ: karaoke/beat` | Tiêu đề có karaoke, instrumental, beat… |
| `không có nội dung để trích xuất` | Mô tả rỗng |
| `ngoài phạm vi: không phải nhạc Việt` | Kênh công ty/chương trình, tiêu đề không có tiếng Việt và không có tên nghệ sĩ seed |

Tên nghệ sĩ một chữ (Ngắn, Min, Orange…) phải khớp nguyên dạng để tránh trùng từ thường.

## Quy tắc đang áp dụng

- Chỉ lưu nội dung xuất bản trong giai đoạn; video trước 2016 chỉ lưu ID để dừng quét.
- Chỉ tự nhận kênh YouTube có tick xanh và tên khớp; kênh fan, reup, Topic bị loại.
- Release dạng `appears_on` chỉ giữ track có nghệ sĩ seed.
- Spotify không trả lượt nghe; release nổi bật xếp theo top-tracks của Spotify (nếu app dùng được), rồi lượt xem MV YouTube cùng tên, rồi album trước single; bản remix/lofi và release ghi hình chương trình xếp sau, mỗi tên bài lấy 1 bản.
- Spotify khóa app Development khi gọi dồn: tool gọi ~1 lần/1,2 giây và dừng cả lượt khi bị chặn, in giờ chạy lại được.
- `document_id` cố định theo ID nền tảng: `DOC_YT_<videoId>`, `DOC_SP_<albumId>`.
- Tài liệu web dùng `DOC_WEB_<hash URL đầu vào>` để redirect không ghi đè link gốc; `resolved_url` và `final_url` được lưu riêng.
- Link chỉ bị coi là trùng khi chuỗi URL đầu vào giống hệt; thay đổi query, fragment, chữ hoa/thường, giao thức hoặc dấu `/` cuối tạo URL riêng.

### Thu thập bài hợp tác, tranh chấp và đại sứ từ graph

Luồng web hỗ trợ Person, Group, Company, Show, Event và Brand đang có trong graph.
Danh mục nguồn gồm VnExpress, Tuổi Trẻ, Thanh Niên, VTV, VOV, Znews, Kênh14 và SaoStar;
đây là nguồn ứng viên, khả năng truy cập phải kiểm tra bằng `web sources-check`.
Thêm website nghệ sĩ/công ty/hãng đĩa/chương trình vào `seeds/web_sources.csv` sau khi
xác minh chủ sở hữu, đặt `source_type=website chính thức`, `site_url`, `enabled=yes`
và `feed_url` nếu có. Không tự xem một website là chính thức chỉ dựa vào tên.
Có thể đưa trực tiếp thông cáo hoặc bài viết vào hàng đợi:

```bash
uv run python main.py web add-urls --entity PER_0001 --url 'https://example.com/bai-viet'
uv run python main.py web discover --entity PER_0001 --search-limit 5 --dry-run
uv run python main.py web discover --entity PER_0001 --search-limit 5 --limit-per-source 100
uv run python main.py web crawl --entity PER_0001 --limit 20 --resolve-limit 10
uv run python main.py web clean
uv run python main.py web signals
```

Thay ID và URL ví dụ bằng thực thể/bài thật. Nguồn ngoài danh mục vẫn được thu thập
 nhưng phải duyệt. Nhập URL giống hệt không tạo thêm mục hàng đợi; provenance vẫn lưu thêm nguồn/query tìm ra nó. Nguồn Wikipedia
 và Wikidata được lưu để kiểm toán nhưng không tải nội dung. Giữ ngày đăng riêng với ngày thu
thập; mốc chốt vẫn là **21/10/2026**, không dùng ngày cập nhật thay ngày đăng.

`web_relation_candidates.csv` lưu ID hai bên, URL, tên nguồn, tiêu đề, ngày đăng,
câu trích, vị trí câu, phương pháp phát hiện và gợi ý `role_detail`. Đây là hàng đợi
bằng chứng để duyệt, chưa phải bảng Relation/Evidence đã xác minh để nhập Neo4j:

- `COLLABORATED_WITH`: chỉ Person–Person; phải kiểm chứng credit cùng tác phẩm trước khi suy ra cạnh.
- `AMBASSADOR_OF`: Person → Brand; phải xác minh vai trò đại sứ, không suy ra từ quảng cáo chung.
- `DISPUTED_WITH`: Person/Company với Person/Company; bao gồm Company–Company.
  Tin đồn, phủ định và tín hiệu yếu như “mâu thuẫn”/“chấm dứt hợp đồng” chờ duyệt,
  không tự mở query cặp. Gợi ý trạng thái cáo buộc/tranh chấp/hòa giải/phán quyết
  không thay kết luận của người duyệt.

Cùng xuất hiện hoặc cùng gameshow không đủ tạo cạnh. Bộ dò theo câu có thể bỏ sót tên
viết tắt, đại từ hoặc bằng chứng nằm ở nhiều câu; cần đọc ngữ cảnh trước khi duyệt.
Tài liệu đã bị loại/trùng và ngoài kỳ không được dùng để phát hiện tín hiệu.
Chạy kiểm thử offline (dữ liệu giả chỉ nằm trong thư mục tạm, không nhập graph):

```bash
uv run python -m unittest discover -s tests -v
```
