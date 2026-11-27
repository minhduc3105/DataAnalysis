# Hướng dẫn chạy phần Đức — VN Music Radar

Chạy từ thư mục gốc repository. Các lệnh dùng `uv` cho Python, `npm` cho React và Docker Compose cho Neo4j/GDS. Dữ liệu nghiên cứu đóng băng đến **21/10/2026**; lane tin mới bắt đầu **22/10/2026**. `.env` hiện có mật khẩu riêng của máy Đức: không ghi đè nếu đã cấu hình.

## Task 1 — Cài dependency, cấu hình môi trường, bật Neo4j/GDS

**Bắt buộc, chạy một lần trên máy.** Docker Compose tải image và plugin GDS ở lần khởi động đầu; cần mạng.

```bash
cp -n .env.example .env
```

Mở `.env` bằng trình soạn thảo và đặt `NEO4J_PASSWORD` dài ít nhất 8 ký tự. Nếu dùng dịch vụ Huy, đặt `MODEL_API_BASE_URL`; `YOUTUBE_API_KEY` là cần thiết để lịch tự thu thập YouTube. Giữ nguyên giá trị Neo4j đang dùng nếu đã có database; đổi mật khẩu trong `.env` không đổi mật khẩu của volume Neo4j cũ.

```bash
uv sync --locked
cd app/web
npm ci
npm run build
cd ../..
docker compose config --quiet
docker compose up -d neo4j
docker compose ps
uv run python main.py doctor
uv run python main.py doctor --neo4j
```

**Kết quả cần thấy:** `docker compose ps` báo service healthy; `doctor` không có `FAIL`; `doctor --neo4j` báo kết nối thành công. Nếu lệnh đầu chưa thấy healthy, đợi thêm một phút rồi xem `docker compose logs neo4j`. Nếu máy đã có Neo4j riêng, chỉnh `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` cho đúng và không cần bật container Compose.

Kiểm tra GDS sau khi Neo4j healthy:

Mở Neo4j Browser tại `http://localhost:7474`, đăng nhập bằng user/password trong `.env`, rồi chạy `RETURN gds.version();`. Docker image được cấu hình plugin `graph-data-science`; lần đầu cài plugin có thể mất vài phút.

## Task 2 — Đóng băng dữ liệu và xuất gói cho Huy

**Bắt buộc, chạy mỗi khi cần phát hành snapshot mới.** Snapshot theo nội dung, không ghi đè snapshot cũ.

```bash
uv run python main.py stage2 freeze
uv run python main.py stage2 export-huy
```

**Đầu ra:** `data/snapshots/research-2016-01-01_2026-10-21-<hash>/manifest.json`, `statistics.json`, `date_review.csv`, bài sạch, từ điển thực thể, quan hệ baseline và quyết định duyệt. Ngày thiếu/mâu thuẫn nằm trong `date_review.csv`, tách khỏi bài nghiên cứu. Gói gửi Huy nằm tại `data/exports/huy/<snapshot-version>/` và có thêm `sample_20.csv`, schema và các tệp baseline. Kiểm tra `manifest.json` trước khi gửi; số bài thật phải khớp dữ liệu Đức đang chốt, không suy ra từ số dự kiến.

Để tạo mẫu gán nhãn 200 bộ ba một lần:

```bash
uv run python main.py gold sample
```

File `data/gold/gold_relations.csv` chia 80 mẫu riêng Đức, 80 mẫu riêng Huy và 40 mẫu chung; `gold_sentences.csv` là mẫu câu gán thực thể/quan hệ bổ sung. Lệnh mặc định không ghi đè file đã có. Không chạy `--force` sau khi bắt đầu gán nhãn trừ khi chủ động bỏ nhãn cũ.

## Task 3 — Nạp baseline vào database dành cho dự án

**Bắt buộc, chạy một lần trên volume/database mới.** Dùng database Compose riêng của dự án.

```bash
uv run python main.py neo4j load
uv run python main.py neo4j check
```

`neo4j load` từ chối nạp đè nếu đã có `:Entity`; đó là bảo vệ dữ liệu. Nếu database đã có entity, chạy `neo4j check` trước và tiếp tục trên database đúng. Chỉ dựng lại database thử nghiệm đã chủ động bỏ được bằng `uv run python main.py neo4j load --reset`; lệnh này xóa toàn bộ dữ liệu trong database đang kết nối.

**Đầu ra cần thấy:** báo cáo trong terminal về entity, quan hệ, document, evidence và kiểm tra liên kết. Trước khi làm giàu, chạy phân tích baseline một lần để lưu mốc so sánh:

```bash
uv run python main.py analyze
```

Đầu ra baseline được lưu dưới `data/interim/analysis/` và `data/interim/analysis/snapshots/graph-<version>/`.

## Task 4 — Crawl tin mới và bật lịch tùy chọn

**`news once` chạy khi cần; `news schedule` là tiến trình định kỳ riêng với web server.** Lượt đầu đọc từ checkpoint hoặc 22/10/2026. Lịch dùng `Asia/Ho_Chi_Minh`: báo và YouTube lúc 07:00 mỗi ngày, Spotify lúc 07:00 thứ Hai.

```bash
uv run python main.py news once
```

**Đầu ra:** `data/interim/web_live_search_report.json`, `web_live_crawl_report.json`, `web_live_quality_report.json`, tài liệu luồng mới, trạng thái bền vững `data/raw/live_update_status.json`, nhật ký độ phủ `data/raw/collection_coverage.jsonl`, và checkpoint riêng theo nguồn. Ngày thiếu/mâu thuẫn được giữ ở review; lỗi crawl/search giữ checkpoint để lượt sau thử lại. Snapshot nghiên cứu không bị ghi đè.

Để chạy thủ công trong terminal riêng:

```bash
uv run python main.py news schedule
```

Dừng tiến trình thủ công bằng `Ctrl+C`. Để tự khởi động cùng phiên đăng nhập và tự chạy lại khi lỗi trên Linux có systemd user service, cài dependency trước rồi chạy:

```bash
scripts/install_news_scheduler_service.sh
systemctl --user status vn-music-radar-scheduler.service
journalctl --user -u vn-music-radar-scheduler.service -f
```

Service dùng `Restart=on-failure`; lệnh cài đặt chỉ ghi unit vào `~/.config/systemd/user`, không chép khóa truy cập. Muốn service hoạt động cả khi chưa đăng nhập, có thể bật linger cho tài khoản bằng `loginctl enable-linger "$USER"` nếu chính sách máy cho phép. Dừng và gỡ tự khởi động bằng `systemctl --user disable --now vn-music-radar-scheduler.service`.

Nếu `YOUTUBE_API_KEY` có trong `.env`, lịch quét tối đa 75 kênh YouTube đã xác minh mỗi lượt và luân phiên offset; nếu khóa vắng, nguồn được đánh dấu thiếu cấu hình và không tính là ngày đủ độ phủ. Spotify cần `SPOTIFY_CLIENT_ID` và `SPOTIFY_CLIENT_SECRET`; giới hạn ngân sách tuần cấu hình bằng `SPOTIFY_WEEKLY_MAX_CALLS` (mặc định 40). Chạy `uv run python main.py news once` khi cần kiểm tra ngay, không cần đợi 07:00.

Lượt lịch thử phân loại chủ đề và sắc thái cho tài liệu luồng mới nếu đã cấu hình `OPENROUTER_API_KEY` (hoặc `OPENAI_API_KEY`) cùng `OPENROUTER_MODEL` (hoặc `WEB_RELATION_REVIEW_MODEL`). Có thể chạy riêng bằng `uv run python main.py classify --limit 25`; giới hạn mặc định là `CONTENT_CLASSIFICATION_DAILY_LIMIT=25`. Kết quả có content hash, phiên bản mô hình, trạng thái, nhãn và trích dẫn trong `data/interim/document_classifications.csv`; trạng thái tác vụ ở `data/raw/content_classification_status.json`. Thiếu khóa/mô hình hoặc lỗi API không sinh nhãn trung tính giả. Trích xuất quan hệ vẫn đi qua model handoff và bước duyệt thủ công bên dưới.

## Task 5 — Nhận kết quả Huy, kiểm tra và nhập tăng dần

**Bắt buộc sau khi Huy bàn giao JSONL.** Mỗi dòng là một kết quả `/extract` theo `schemas/model_contract_v1.json`. Đặt file tại `data/interim/model_handoff/extractions.jsonl`:

```bash
mkdir -p data/interim/model_handoff
cp /duong/dan/huy/extractions.jsonl data/interim/model_handoff/extractions.jsonl
uv run python main.py stage2 validate
```

Nếu có lỗi, xem `data/interim/model_handoff/validation_errors.json`, sửa dữ liệu nguồn/contract rồi chạy validate lại. Fixture phải có `is_fixture: true` và `fixture_text`; fixture không đi vào liên kết hay nhập đồ thị.

Liên kết mention. Nếu API `/embed` của Huy đã chạy, dùng lệnh đầu để xếp hạng ứng viên theo embedding; nếu chưa, dùng khớp tên/alias và gợi ý gần tên:

```bash
uv run python main.py stage2 link --embeddings
# hoặc khi /embed chưa sẵn sàng:
uv run python main.py stage2 link
```

Mở `entity_link_review.csv` và `relation_review.csv`. Khớp chính xác, duy nhất theo đúng loại có `linked_entity_id` điền sẵn; mention mơ hồ/chưa khớp phải được người duyệt chọn ID hoặc đặt `decision=accepted_new`; không được tự gộp chỉ vì embedding gần. Chỉ đặt `decision=accepted` cho quan hệ có hướng/kiểu đúng và câu bằng chứng nguyên văn, đủ ngữ cảnh. Với mỗi quan hệ accepted, điền `reviewed_by`, `reviewed_at` ISO-8601 kèm múi giờ (ví dụ `2026-11-25T10:00:00+07:00`) và `decision_note`; ghi `rejected` nếu không đủ chứng cứ. Chạy lại `stage2 link` sẽ giữ các cột đã duyệt khi khóa mention/quan hệ vẫn khớp.

Kiểm tra trước khi ghi:

```bash
uv run python main.py stage2 import --dry-run
```

Dry-run kiểm tra bảng duyệt và bằng chứng local, không kết nối/ghi Neo4j. Nhập tăng dần sau khi review:

```bash
uv run python main.py stage2 import
uv run python main.py neo4j check
```

Nhập dùng ID ổn định và `MERGE`; có thể chạy lại sau lỗi mà không nhân đôi node/evidence/review event. Mỗi lần duyệt được lưu thành `:ReviewEvent` gắn với evidence, có người duyệt, thời gian, lý do, model/schema và checksum batch trích xuất. Xem lịch sử trong Neo4j hoặc báo cáo `data/interim/model_handoff/import_report_*.json`. Lệnh mặc định không xóa database.

## Task 6 — Phân tích trước/sau làm giàu và tạo 15 câu hỏi

**Bắt buộc sau baseline và sau nhập.** Lượt đầu ghi mốc; lượt tiếp theo ghi thay đổi cùng snapshot đồ thị.

```bash
uv run python main.py analyze
```

Sau import, chạy lại lệnh này. Mở `data/interim/analysis/analysis_manifest.json` để xác nhận `graph_version`, khoảng thời gian, seed, thời điểm và số nút/cạnh. Bảng/ảnh nằm dưới `data/interim/analysis/snapshots/graph-<version>/`; các bảng so sánh gồm `graph_enrichment_delta.csv`, `pagerank_change_after_enrichment.csv`, `community_bridges.csv`, `small_world_reference_runs.csv` và `pagerank_by_period.csv`.

Tạo 15 câu hỏi ứng viên dựa trên đường đi 2–3 bước có evidence được duyệt:

```bash
uv run python main.py gold multi-hop --count 15
```

Đầu ra `data/gold/multihop_duc.jsonl` ghi câu hỏi, đáp án đường đi, evidence URL/ID và `graph_version`. Đức phải rà soát câu hỏi và đáp án trước khi gửi Huy. Lệnh giữ nguyên file đã tồn tại; chỉ dùng `--force` nếu chủ động thay bộ đã gán nhãn.

## Task 7 — Embedding, vector index và tóm tắt cộng đồng

**Cần API thật của Huy tại `MODEL_API_BASE_URL`.** Kiểm tra hợp đồng embedding trước khi tạo index:

```bash
uv run python main.py doctor --model
uv run python main.py neo4j indexes
uv run python main.py neo4j embed
```

`indexes` lấy model version/số chiều trực tiếp từ `/embed`, tạo vector index cho Evidence và Entity; `embed` thêm vector cho bằng chứng và tên/alias thực thể chưa có. Nếu Huy đổi model hoặc chiều, chạy lại `neo4j indexes` rồi `neo4j embed` để tái tạo vector. Không tự điền số chiều đoán.

Xuất đầu vào cho Huy tóm tắt cộng đồng:

```bash
uv run python main.py stage2 communities-export
```

Gửi `data/interim/model_handoff/communities_for_summary.json` cho Huy. Huy trả một JSON object mỗi dòng tại `data/interim/model_handoff/community_summaries.jsonl`, gồm `community_id`, `schema_version`, `model_version`, `summary`, `source_ids`; `source_ids` phải là `evidence_id` trong gói đã xuất của cộng đồng tương ứng. Nhập sau khi Huy trả kết quả:

```bash
uv run python main.py stage2 communities-import
```

Tóm tắt thiếu model version hoặc nguồn hợp lệ sẽ bị từ chối. API không tạo câu trả lời thay khi thiếu model/bằng chứng.

## Task 8 — Chạy backend/frontend và demo

Mở hai terminal tại thư mục gốc. Backend:

```bash
uv run uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd app/web
npm run dev
```

Mở `http://localhost:5173`. Kiểm tra `http://127.0.0.1:8000/api/health` trả `ok: true`. Sáu màn hình: Bảng tin, Theo dõi và cảnh báo, Xu hướng, Vì sao liên quan, Hỏi đáp, Chân dung mạng. Các màn hình mạng cần chạy `analyze`; Hỏi đáp cần Neo4j có evidence, API `/answer`, và vector method cần hoàn tất Task 7.

### Kịch bản demo đề xuất

1. Mở Bảng tin, lọc nguồn/ngày, bấm mở một bài gốc.
2. Tìm và theo dõi một nghệ sĩ; xem bằng chứng/cảnh báo và ghi nhận nếu chưa đủ lịch sử.
3. Chọn thực thể trong Vì sao liên quan, giới hạn ba bước, lọc thời gian; mở từng URL bằng chứng.
4. Gửi câu multi-hop có trong `multihop_duc.jsonl` một lần bằng GraphRAG, một lần bằng Vector; kiểm tra trích dẫn có nằm trong nguồn trả về.
5. Mở Xu hướng và Chân dung mạng; giải thích snapshot, graph version và khoảng thời gian trên manifest.
6. Chỉ trình bày câu trả lời/tóm tắt từ API thật; nêu rõ dữ liệu fixture nếu dùng để thử giao diện.

## Tích hợp và xử lý lỗi

Kiểm thử offline/build nhẹ (không cần Neo4j hoặc API Huy):

```bash
uv run python -m unittest discover -s tests -v
cd app/web && npm run build
```

Kiểm thử tích hợp sau khi task 1–3 đã chạy:

```bash
uv run python main.py doctor --neo4j --model
uv run python main.py neo4j check
uv run python main.py stage2 import --dry-run
curl -fsS http://127.0.0.1:8000/api/health
```

Sau khi backend chạy và đã hoàn tất Task 7, chạy kịch bản kiểm tra đọc-only cho feed, watchlist, alert, trend, snapshot phân tích, GDS và index. Lệnh không ghi vào Neo4j. Có thể cung cấp câu hỏi đã biết có bằng chứng để kiểm tra cả câu trả lời GraphRAG/vector và citation:

```bash
scripts/check_stage2_integration.sh
MUSIC_RADAR_INTEGRATION_QUESTION='Nghệ sĩ A liên quan thế nào đến bài hát B?' scripts/check_stage2_integration.sh
```

Thay câu ví dụ bằng câu hỏi có đường đi/bằng chứng thật. Kịch bản không tự tạo câu trả lời giả; nếu câu hỏi chưa có bằng chứng, kiểm tra sẽ dừng và ghi rõ phương thức nào thiếu kết quả.

- Docker không lên: `docker compose logs neo4j`; kiểm tra port 7474/7687 và `NEO4J_PASSWORD` trong `.env`.
- Database cũ từ chối `neo4j load`: không thêm `--reset` theo thói quen; xác nhận URI/database và chạy `neo4j check`.
- GDS không có: kiểm tra `RETURN gds.version();`, plugin trong image và log khởi động; sau đó restart service.
- `stage2 validate` lỗi: đọc JSONL và `validation_errors.json`; mention/evidence phải nằm nguyên văn trong document ID, relation phải đúng schema/hướng.
- `stage2 import` thiếu ID: sửa `linked_entity_id` trong bảng duyệt để trỏ vào Entity đúng type đang có trong Neo4j.
- `/embed` timeout/đổi chiều: kiểm tra service Huy, URL và model version; chạy lại `doctor --model`, `neo4j indexes`, `neo4j embed`.
- `news once` không tăng checkpoint: xem hai report live; lỗi nguồn/crawl sẽ giữ nguyên checkpoint để thử lại ở lượt sau.
- React không gọi được API: giữ backend chạy ở cổng 8000; Vite proxy `/api` tới `127.0.0.1:8000`.

Không đưa số liệu thật vào báo cáo cho đến khi command tạo ra manifest/report tương ứng. Test offline, build, dữ liệu fixture, phân tích trên đồ thị thật và đánh giá API Huy là bốn trạng thái khác nhau.
