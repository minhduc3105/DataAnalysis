# VN Music Network

**Thu thập dữ liệu và xây dựng mạng lưới ca sĩ, nhạc sĩ, nhóm nhạc và công ty giải trí Việt Nam.**

Dự án kết hợp dữ liệu YouTube, Spotify, báo chí và website để trích xuất thực thể, xác định quan hệ có bằng chứng và phân tích mạng lưới bằng Neo4j Graph Data Science. Quy trình gồm thu thập, chuẩn hóa, duyệt dữ liệu và xuất đồ thị phục vụ nghiên cứu.

- **Phạm vi dữ liệu:** 01/01/2016–21/10/2026.
- **Công nghệ:** Python ≥ 3.11, uv, pandas, yt-dlp, Playwright, Neo4j.
- **Đề tài:** Đề tài 23 — xem mục tiêu, mô hình dữ liệu và câu hỏi nghiên cứu trong [kế hoạch nghiên cứu](Plan.md).

> Kết quả trích xuất tự động là dữ liệu ứng viên. Cần kiểm tra bằng chứng và trạng thái duyệt trước khi sử dụng để kết luận về quan hệ giữa các thực thể.

## Mục lục

- [Tính năng](#tính-năng)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Cài đặt và cấu hình](#cài-đặt-và-cấu-hình)
- [Quy trình sử dụng](#quy-trình-sử-dụng)
- [Thu thập và xử lý dữ liệu web](#thu-thập-và-xử-lý-dữ-liệu-web)
- [Neo4j và phân tích mạng](#neo4j-và-phân-tích-mạng)
- [Dữ liệu đầu ra](#dữ-liệu-đầu-ra)
- [Quy tắc chất lượng dữ liệu](#quy-tắc-chất-lượng-dữ-liệu)
- [Kiểm thử](#kiểm-thử)
- [Đóng góp](#đóng-góp)

## Tính năng

- Khởi tạo danh sách nghệ sĩ từ playlist chương trình và chuyển ứng viên đã duyệt thành danh sách thu thập.
- Tìm kênh YouTube, Spotify artist ID; thu thập video, bản phát hành, credit và thông tin bản quyền.
- Khám phá bài viết qua RSS, sitemap và Google News RSS; lưu HTML, nguồn phát hiện và tiến độ xử lý.
- Trích xuất người, nhóm nhạc, bài hát, album, công ty, thương hiệu và chương trình; lưu câu trích làm bằng chứng cho quan hệ.
- Duyệt tín hiệu quan hệ từ báo chí, xây dựng đồ thị web riêng và hỗ trợ rà soát ngữ nghĩa qua OpenRouter.
- Xuất bảng CSV, trang HTML xem đồ thị và dữ liệu Gephi; phân tích cộng đồng và độ trung tâm bằng Neo4j GDS.

## Cấu trúc dự án

```text
.
├── main.py               # Điểm vào CLI
├── crawler/              # Thu thập, chuẩn hóa, trích xuất và phân tích
├── seeds/                # Thực thể khởi tạo, nguồn web và quy tắc hiệu chỉnh
├── data/
│   ├── raw/              # Dữ liệu nguồn, HTML và checkpoint thu thập
│   ├── interim/          # Tài liệu, ứng viên, đồ thị tổng và kết quả phân tích
│   └── processed/web/    # Bài viết chuẩn hóa và đồ thị web đã duyệt
├── neo4j/queries.cypher   # Truy vấn minh họa cho Neo4j Browser
├── tests/                # Kiểm thử luồng web
├── .env.example          # Mẫu cấu hình môi trường
├── pyproject.toml        # Thông tin dự án và phụ thuộc
├── uv.lock               # Khóa phiên bản phụ thuộc
└── Plan.md               # Kế hoạch nghiên cứu
```

Các thư mục đầu ra được tạo khi chạy quy trình tương ứng. `.env`, `.venv/`, `data/raw/` và `logs/` được loại khỏi Git qua `.gitignore`.

## Cài đặt và cấu hình

### Yêu cầu

- Python **3.11 trở lên** và **uv**.
- Kết nối mạng khi thu thập dữ liệu hoặc gọi API rà soát ngữ nghĩa.
- Neo4j có plugin **Graph Data Science** nếu chạy phân tích mạng.
- Chromium của Playwright nếu dùng tùy chọn `--browser-fallback`.

### Cài đặt

Từ thư mục gốc của repository, cài phụ thuộc:

```bash
uv sync --locked
```

Tạo tệp cấu hình trên Linux/macOS:

```bash
cp .env.example .env
```

Hoặc trên Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Điền các biến cần thiết trong `.env` theo chức năng sử dụng:

| Biến | Mục đích | Khi nào cần |
| --- | --- | --- |
| `YOUTUBE_API_KEY` | Truy cập YouTube Data API | Tùy chọn; chế độ `auto` dùng yt-dlp nếu không có key |
| `SPOTIFY_CLIENT_ID` | Client ID của ứng dụng Spotify | Khi dùng lệnh `spotify` |
| `SPOTIFY_CLIENT_SECRET` | Client secret của ứng dụng Spotify | Khi dùng lệnh `spotify` |
| `NEO4J_URI` | Địa chỉ database; mặc định `neo4j://localhost:7687` | Khi dùng Neo4j |
| `NEO4J_USER` | Tên đăng nhập; mặc định `neo4j` | Khi dùng Neo4j |
| `NEO4J_PASSWORD` | Mật khẩu database | Khi dùng Neo4j |

Không đưa khóa API hoặc mật khẩu vào repository. Nếu cần trình duyệt dự phòng cho luồng web, cài Chromium một lần:

```bash
uv run playwright install chromium
```

Kiểm tra CLI và danh sách thực thể khởi tạo:

```bash
uv run python main.py --help
uv run python main.py seeds
```

## Quy trình sử dụng

### 1. Khởi tạo từ chương trình âm nhạc

Bỏ qua bước này nếu đã có danh sách phù hợp trong `seeds/seeds.csv`.

```bash
uv run python main.py shows crawl
uv run python main.py layer1 extract
```

Kiểm tra các bảng trong `data/interim/` trước khi chuyển ứng viên thành seeds:

| Tệp | Nội dung cần duyệt |
| --- | --- |
| `layer1_candidates.csv` | Tên người/nhóm, vai trò, kênh YouTube; điền `approve=y/n`, sửa `entity_type` nếu cần |
| `layer1_songs.csv` | Tên bài hát, nghệ sĩ, credit và mashup; điền `approve`, `review_note` |
| `layer1_orgs.csv` | Công ty, thương hiệu và bằng chứng; điền `approve`, sửa `entity_type` nếu cần |

```bash
uv run python main.py layer2 promote
```

Cột `title_order` trong `seeds/shows.csv` hỗ trợ `song-artist`, `artist-song`, `artist|song`, `free` và `mascot`. Thêm tên rút sai vào `seeds/layer1_blocklist.txt`. Chạy lại `layer1 extract` giữ các cột đã duyệt.

### 2. Thu thập YouTube và Spotify

```bash
uv run python main.py youtube resolve
uv run python main.py youtube crawl
uv run python main.py spotify resolve
uv run python main.py spotify crawl
```

YouTube chỉ tự nhận kênh có dấu xác minh và tên khớp; Spotify chỉ tự điền artist ID khi có một kết quả trùng tên duy nhất. Kiểm tra bảng ứng viên nếu chưa xác định được tài khoản chính thức.

Có thể giới hạn phạm vi chạy:

```bash
uv run python main.py youtube crawl --seed SEED_001 SEED_002
uv run python main.py spotify crawl --seed SEED_001 --top 5
```

Thay ID ví dụ bằng `seed_id` thực tế. Spotify mặc định lấy chi tiết 5 bản phát hành nổi bật cho mỗi nghệ sĩ; dùng `--top 0` để lấy tất cả. Các lệnh thu thập hỗ trợ chạy tiếp và bỏ qua mục đã có theo checkpoint.

### 3. Chuẩn hóa và dựng đồ thị tổng

```bash
uv run python main.py documents
uv run python main.py extract
uv run python main.py graph
uv run python main.py view
uv run python main.py stats
```

Mở `data/interim/graph/viewer.html` để xem đồ thị. Sau khi sửa seeds hoặc thu thập thêm, chạy lại chuỗi `documents` → `extract` → `graph`; chạy lại `view` để cập nhật trang xem.

ID thực thể và quan hệ được duy trì qua `data/interim/graph/id_registry.csv`. Giữ tệp này khi cần tái dựng đồ thị với ID ổn định.

## Thu thập và xử lý dữ liệu web

Luồng web sử dụng nguồn trong `seeds/web_sources.csv` và thực thể từ `data/interim/graph/entities.csv`. Cần dựng đồ thị tổng trước khi tìm bài viết theo thực thể.

### Khám phá và tải bài viết

```bash
uv run python main.py web sources-check
uv run python main.py web discover --dry-run
uv run python main.py web discover --search-limit 50
uv run python main.py web crawl --limit 100
uv run python main.py web clean
uv run python main.py web signals
uv run python main.py web stats
```

Các tùy chọn thường dùng:

| Tùy chọn | Áp dụng | Ý nghĩa |
| --- | --- | --- |
| `--entity PER_0001` | `discover`, `crawl` | Giới hạn theo ID thực thể thực tế |
| `--from 2024-01-01 --to 2024-12-31` | `discover` | Giới hạn kỳ tìm kiếm |
| `--search-limit 50` | `discover` | Số query Google News tối đa mỗi lượt |
| `--limit-per-source 1000` | `discover` | Số URL sitemap tối đa đọc mỗi nguồn |
| `--limit 100` | `crawl` | Số URL tối đa xử lý mỗi lượt |
| `--resolve-limit 50` | `crawl` | Số link Google News tối đa tự giải mỗi lượt |
| `--workers 8` | `crawl` | Số tác vụ tải song song tối đa |
| `--browser-fallback` | `crawl` | Dùng Chromium khi HTTP chưa lấy đủ dữ liệu |

Có thể thêm trực tiếp URL bài gốc vào hàng đợi:

```bash
uv run python main.py web add-urls --entity PER_0001 --url 'https://example.com/bai-viet'
```

Thay ID và URL ví dụ bằng dữ liệu thực tế. Với link Google News cần xử lý thủ công, dùng `web review-export`, cập nhật `web_candidates.csv`, rồi chạy `web review-import`. Dùng `web recover-urls --dry-run` để xem các URL lịch sử có thể phục hồi trước khi chạy `web recover-urls`.

Checkpoint nằm tại `data/raw/web/crawl.sqlite3`. Luồng tải giữ riêng URL đầu vào, URL đã giải và URL cuối sau chuyển hướng; chỉ chuỗi URL đầu vào giống hệt mới được xem là trùng. Nội dung giống nhau được đánh dấu bằng `duplicate_content_of` thay vì xóa URL.

### Chuẩn hóa và duyệt đồ thị web riêng

Các lệnh sau xử lý dữ liệu đã thu thập, xuất kết quả vào `data/processed/web/` và không ghi vào đồ thị tổng:

```bash
uv run python main.py web recover-data --dry-run
uv run python main.py web recover-data
uv run python main.py web merge-data --dry-run
uv run python main.py web merge-data
uv run python main.py web normalize
uv run python main.py web relations
```

`recover-data` phục hồi dữ liệu từ HTML còn lưu; `merge-data` hợp nhất CSV, JSONL lịch sử và dữ liệu phục hồi. `normalize` phân loại bài viết, nhóm trùng và liên kết thực thể. `relations` tạo ứng viên cùng sổ quyết định `relation_decisions.csv`, mặc định chưa duyệt (`unreviewed`).

Duyệt một tín hiệu bằng ID thực tế và lý do dựa trên bằng chứng:

```bash
uv run python main.py web decide-relation --signal-id SIG_ID --decision accepted --reviewer "Tên người duyệt" --reason "Câu trong bài xác nhận quan hệ"
uv run python main.py web graph-build
```

`--decision` nhận `accepted`, `rejected` hoặc `unverified`. Để duyệt hàng loạt, sửa `review_status`, `decision_reason`, `reviewed_by` trong `relation_decisions.csv`, giữ nguyên `candidate_content_hash`, rồi chạy:

```bash
uv run python main.py web apply-decisions
uv run python main.py web graph-build
```

Chỉ tín hiệu `accepted` có hash nội dung hiện hành, URL, câu trích và hai ID thực thể hợp lệ mới được xuất thành cạnh trong `graph_clean/`. Kiểm tra `quality_report.json`, `relation_report.json` và `graph_report.json` để đánh giá kết quả.

### Rà soát ngữ nghĩa bằng OpenRouter — tùy chọn

Thêm cấu hình vào `.env`:

```dotenv
OPENROUTER_API_KEY=your_api_key
OPENROUTER_MODEL=provider/model
```

Mã nguồn cũng hỗ trợ tên biến `OPENAI_API_KEY` và `WEB_RELATION_REVIEW_MODEL`. Endpoint mặc định là `https://openrouter.ai/api/v1`; có thể đổi bằng `OPENROUTER_BASE_URL`. Header ứng dụng tùy chọn dùng `OPENROUTER_HTTP_REFERER` và `OPENROUTER_APP_TITLE`.

```bash
uv run python main.py web semantic-review --dry-run
uv run python main.py web semantic-review --limit 1
uv run python main.py web semantic-review
```

`--dry-run` chỉ ước lượng khối lượng, không gọi API. Khi chạy thật, mỗi quan hệ được gửi cùng bằng chứng và ngữ cảnh; kết quả được checkpoint sau từng quan hệ. Dùng `--force` để rà lại kết quả đã có.

Kết quả nằm trong `graph_clean/relation_semantic_review.csv`; lệnh rà soát không tự sửa quyết định hoặc đồ thị. Sau khi kết quả bao phủ toàn bộ quan hệ và bằng chứng hiện tại, có thể áp dụng bằng:

```bash
uv run python main.py web apply-semantic-review --dry-run
uv run python main.py web apply-semantic-review
```

Lệnh áp dụng chuyển tín hiệu hỗ trợ quan hệ `invalid` thành `rejected`, `uncertain` thành `unverified`, giữ quyết định với `valid`, rồi dựng lại đồ thị. Kết quả rà soát cũ được lưu thành bản archive.

## Neo4j và phân tích mạng

Khởi động database Neo4j, cài plugin Graph Data Science và cấu hình các biến `NEO4J_*` trước khi chạy.

> [!WARNING]
> `neo4j load` xóa dữ liệu hiện có trong database đích trước khi nạp đồ thị tổng từ `data/interim/graph/`. Lệnh này không dùng để nạp đồ thị web riêng trong `data/processed/web/graph_clean/`.

```bash
uv run python main.py neo4j load
uv run python main.py neo4j check
uv run python main.py analyze
```

Phân tích gồm WCC, Louvain, PageRank, Betweenness và Degree. Mạng hợp tác sử dụng nút Person/Group, cạnh `COLLABORATED_WITH` vô hướng và trọng số bằng số bài khác nhau cùng trình bày. Quy trình chạy cả phiên bản có và không có cạnh chỉ đến từ tiết mục chương trình (`show_only`) để kiểm tra độ ổn định.

- Kết quả phân tích: `data/interim/analysis/`.
- Tệp nhập Gephi: `gephi_nodes.csv` và `gephi_edges.csv` trong thư mục kết quả.
- Truy vấn Neo4j Browser: [neo4j/queries.cypher](neo4j/queries.cypher).

Nút `Document`, `Evidence` và cạnh `FROM_DOCUMENT` dùng để truy nguồn, không tính vào chỉ tiêu mạng thực thể. Trường `first_year` lấy năm đăng sớm nhất trong bằng chứng; với YouTube, đây là giá trị xấp xỉ năm phát hành.

## Dữ liệu đầu ra

| Đường dẫn | Nội dung |
| --- | --- |
| `data/raw/youtube/<channel_id>.jsonl` | Video và metadata YouTube |
| `data/raw/spotify/releases/<artist_id>.jsonl` | Danh sách bản phát hành trong kỳ |
| `data/raw/spotify/albums/<artist_id>.jsonl` | Chi tiết bản phát hành, track và bản quyền |
| `data/interim/documents.csv` | Bảng tài liệu YouTube/Spotify đã chuẩn hóa |
| `data/interim/mentions.csv` | Tên được trích xuất, vai trò, câu trích và vị trí |
| `data/interim/social_handles.csv` | Tài khoản mạng xã hội ứng viên theo nghệ sĩ |
| `data/interim/graph/` | `entities.csv`, `relations.csv`, `evidence.csv` và sổ ID |
| `data/interim/web_documents.csv` | Bài viết web sau làm sạch |
| `data/interim/document_entities.csv` | Liên kết tài liệu web–thực thể ứng viên |
| `data/interim/web_relation_candidates.csv` | Tín hiệu quan hệ từ luồng `web signals` |
| `data/interim/web_search_report.json` | Báo cáo tìm kiếm và trạng thái query |
| `data/interim/web_crawl_report.json` | Báo cáo tải bài, trường còn thiếu và lỗi |
| `data/processed/web/` | Bài viết chuẩn hóa, ứng viên và sổ quyết định duyệt |
| `data/processed/web/graph_clean/` | Đồ thị web chỉ chứa bằng chứng đã được chấp nhận |
| `data/interim/analysis/` | Kết quả thuật toán mạng và bảng xuất Gephi |
| `logs/crawl_runs.csv` | Nhật ký thu thập và lỗi theo nguồn |

`documents.csv` gồm 13 trường Document theo [Plan.md](Plan.md), bổ sung `platform`, `platform_item_id`, `seed_ids`. Nội dung YouTube là mô tả video gốc; nội dung Spotify là văn bản ghép từ dữ liệu API, không phải bài viết gốc.

## Quy tắc chất lượng dữ liệu

### Phạm vi và bằng chứng

- Video ngắn ≤ 60 giây hoặc có `#shorts` được lọc ở bước thu thập. Các bộ lọc nội dung tiếp theo phụ thuộc loại kênh và dấu hiệu âm nhạc.
- Khi xuất tài liệu, nội dung được gắn nhãn `mv_audio`, `performance_show`, `brand`, `release` hoặc `other`. Bản karaoke/beat, mô tả rỗng và nội dung ngoài phạm vi nhạc Việt có thể bị loại kèm lý do.
- Video gộp nhiều bài không được gán credit cho từng bài. MCN không được xem là công ty phát hành chỉ từ thông tin bản quyền.
- Quan hệ và bằng chứng của đồ thị tổng mặc định ở trạng thái chờ kiểm tra; thực thể ngoài seeds chưa được xem là đã xác minh.
- Cùng xuất hiện trong một bài viết hoặc gameshow chưa đủ để tạo quan hệ. Bộ dò theo câu có thể bỏ sót đại từ, tên viết tắt hoặc bằng chứng trải trên nhiều câu.
- Ngày xuất bản bài web được xác minh lại từ bài gốc. Trang thiếu trường, ngày mâu thuẫn hoặc chưa rõ liên quan được giữ để duyệt.
- ID tài liệu dựa trên ID nền tảng (`DOC_YT_<videoId>`, `DOC_SP_<albumId>`) hoặc hash URL đầu vào (`DOC_WEB_<hash>`).

### Hiệu chỉnh thực thể

Cập nhật các tệp sau, rồi chạy lại bước xử lý liên quan:

| Tệp trong `seeds/` | Công dụng |
| --- | --- |
| `aliases.csv` | Gộp tên gọi của cùng nghệ sĩ |
| `company_aliases.csv` | Chuẩn hóa tên công ty |
| `entity_blocklist.csv` | Loại tên bị trích xuất sai |
| `entity_overrides.csv` | Điều chỉnh loại thực thể, tên chuẩn hoặc đánh dấu `drop` |
| `excluded_seeds.csv` | Loại thực thể khỏi quá trình tạo mention |
| `show_roles.csv` | Nhận diện HLV/giám khảo để tránh gán nhầm thành thí sinh |
| `web_sources.csv` | Quản lý nguồn báo chí và website đã xác minh |
| `web_relation_terms.csv` | Điều chỉnh từ khóa phát hiện tín hiệu quan hệ |

### Giới hạn nguồn dữ liệu

Spotify không cung cấp lượt nghe trong luồng hiện tại. Bản phát hành nổi bật được xếp theo top-tracks nếu truy cập được, lượt xem MV YouTube cùng tên và loại bản phát hành. Thông tin công ty phát hành có thể lấy từ dòng ℗/© khi trường label không có.

Khả năng truy cập API và website phụ thuộc nguồn. Dùng `web sources-check`, báo cáo crawl và nhật ký lỗi để kiểm tra; nếu Spotify yêu cầu chờ do giới hạn truy cập, chạy lại theo thời điểm công cụ thông báo.

## Kiểm thử

Chạy bộ kiểm thử offline cho luồng web:

```bash
uv run python -m unittest discover -s tests -v
```

Dữ liệu kiểm thử được tạo trong thư mục tạm, không nhập vào đồ thị nghiên cứu. Tra cứu tùy chọn CLI bằng:

```bash
uv run python main.py --help
uv run python main.py web --help
```