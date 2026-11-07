# Mạng lưới Ca sĩ – Nhạc sĩ – Công ty giải trí Việt Nam

Đề tài 23, xem [Plan.md](Plan.md). Giai đoạn dữ liệu: 01/01/2016 – 31/10/2026.

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
uv run python main.py spotify crawl             # release → track, label, bản quyền
uv run python main.py documents                 # xuất data/interim/documents.csv (bảng Document)
uv run python main.py extract                   # rút credit, bài hát, album, label, brand, handle MXH → mentions.csv, social_handles.csv
uv run python main.py graph                     # dựng bảng Entity/Relation/Evidence → data/interim/graph/
uv run python main.py stats
```

Chạy lại `documents → extract → graph` mỗi khi sửa seeds hoặc crawl thêm. ID trong `graph/` (PER_, SON_, REL_…) được giữ cố định qua `graph/id_registry.csv`.

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
| `data/raw/spotify/albums/<artist_id>.jsonl` | Release thô kèm track (không commit) |
| `data/interim/documents.csv` | Bảng `Document` theo Bước 2 của Plan.md |
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
- `document_id` cố định theo ID nền tảng: `DOC_YT_<videoId>`, `DOC_SP_<albumId>`.
