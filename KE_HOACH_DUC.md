# Kế hoạch hoàn thiện phần Đức — VN Music Radar

Phạm vi lấy `Phân công giai đoạn 2 – Đức và Huy.md` làm chuẩn. Tài liệu này tách rõ phần đã viết, phần đã kiểm thử trong môi trường local và phần chỉ được xác nhận khi Đức chạy dữ liệu/Docker/API thật.

## Trạng thái triển khai

| Nhóm việc | Đối chiếu đầu việc | Code/đầu ra | Trạng thái hiện tại |
|---|---|---|---|
| Đóng băng dữ liệu nghiên cứu | 5.240 bài đến 21/10/2026; kiểm tra ID, URL, nguồn, ngày; thống kê và gói cho Huy | `crawler/stage2.py`; snapshot bất biến dưới `data/snapshots/`; gói Huy dưới `data/exports/huy/`; gồm bài, từ điển ID/alias, quan hệ baseline, quyết định duyệt, thống kê và 20 bài | **Đã code**; kiểm thử snapshot bằng dữ liệu tạm; cần Đức chạy để xác nhận số liệu thật và lưu manifest thật |
| Tách dữ liệu mới | Luồng báo/video từ 22/10/2026; ngày thiếu/mâu thuẫn cần duyệt | `crawler/web.py`, `crawler/web_clean.py`, `crawler/youtube.py`, `crawler/documents.py`; tách file lane research/live; báo cáo riêng | **Đã code**; cần chạy crawl để kiểm tra nguồn thật |
| Crawl và checkpoint | Khoảng ngày, giới hạn lượt, chạy tiếp sau lỗi, lịch 07:00 giờ Việt Nam | `news once`, `news schedule`; SQLite giữ URL/query; `data/raw/web/live_checkpoint.json` giữ checkpoint báo và offset kênh YouTube | **Đã code**; lịch chỉ chạy khi tiến trình được bật; cần kiểm tra API/quota và crawler thật |
| Hợp đồng Huy | `/extract`, `/embed`, `/answer`, `/summarize`; schema và mẫu | `schemas/model_contract_v1.json`, `schemas/extract_example_v1.json`, `crawler/model_contract.py`; HTTP timeout/retry và kiểm tra chiều embedding | **Đã code**; kiểm thử offline bằng fixture; chờ Huy chạy API thật |
| Liên kết thực thể | Khóa/tên/alias; gợi ý embedding; mơ hồ chờ duyệt | `stage2 link` tạo bảng duyệt; `stage2 link --embeddings` xếp hạng gợi ý bằng `/embed`; loại thực thể được kiểm tra; không tự gộp mention mơ hồ | **Đã code**; kiểm thử logic hợp đồng; cần người duyệt và dữ liệu Neo4j thật |
| Hậu kiểm và nhập tăng dần | Hướng cạnh, kiểu nút, bằng chứng nguyên văn, ID ổn định, checkpoint/idempotency, lịch sử duyệt, không xóa DB | `stage2 validate`, `stage2 import --dry-run`, `stage2 import`; `:ReviewEvent` gắn reviewer/time/source/model/batch; `crawler/graphdb.py` chỉ reset khi có `--reset` rõ ràng | **Đã code**; test xác thực offline; nhập Neo4j và khả năng tiếp tục sau gián đoạn chờ Đức chạy tích hợp |
| Chất lượng đồ thị | Schema, nút trùng/cô lập, độ phủ bằng chứng, so sánh trước/sau | `stage2 import` lưu báo cáo quality trước/sau; `analysis` xuất `graph_enrichment_delta.csv`, `pagerank_change_after_enrichment.csv` | **Đã code; snapshot/test logic offline đã kiểm tra**; cần Đức nhập trên Neo4j để có báo cáo chất lượng số liệu thật |
| Phân tích mạng | PageRank có trọng số, degree, betweenness, eigenvector, vai trò, hai kỳ, cộng đồng, k-core, cầu nối, thế giới nhỏ | `crawler/analysis.py`; kỳ `2016–2020`, `2021–2026`; 20 đồ thị Erdős–Rényi và 20 hoán đổi bậc; lattice tham chiếu; kết quả có graph version/seed/thời điểm | **Đã code**; chưa chạy GDS trên database thật; cần xử lý bất kỳ lỗi phiên bản/plugin khi chạy |
| GraphRAG và vector đối chứng | Tối đa ba bước; lọc loại cạnh/thời gian; bằng chứng; citations; index embedding | `crawler/retrieval.py`; API `/api/ask`; vector index cho Evidence/Entity qua `neo4j indexes`, `neo4j embed`; đổi model/chiều sẽ yêu cầu tái tạo embedding | **Đã code; test offline và build frontend đã chạy**; endpoint mô hình thật, index và độ đúng câu trả lời chưa kiểm thử tích hợp |
| Backend và sáu màn hình | Feed, watchlist/alerts, trend, explain, ask, network | `app/api/main.py`; `app/web/src/pages/`; lưu watchlist trong Neo4j; cảnh báo trong ứng dụng | **Đã code; 38 test offline qua và build React thành công**; cần API Neo4j thật để demo |
| Gán nhãn và bộ hỏi | Đức 80 mẫu riêng + 40 mẫu chung; 15 câu hỏi multi-hop | `gold sample` tạo mẫu có phân công; `gold multi-hop` tạo 15 câu có đường đi, nguồn và graph version | **Đã code công cụ**; Đức phải gán nhãn và rà soát câu hỏi ứng viên |
| Docker và môi trường | Neo4j + GDS, volume, uv, npm, kiểm tra môi trường | `docker-compose.yml`, `.env.example`, `pyproject.toml`, `uv.lock`, `doctor` | **Đã cấu hình; dependency khóa và CLI đã kiểm tra**; cần Đức nhập mật khẩu và tự khởi động Docker |
| Kiểm thử tích hợp | Kiểm tra Neo4j, GDS, index, API và citation trên máy Đức | `scripts/check_stage2_integration.sh` | **Đã code; shell syntax đã kiểm tra**; chỉ chạy sau khi Đức khởi động Neo4j/backend và có model thật |
| Báo cáo/demo | Dữ liệu, đồ thị, phân tích, ứng dụng và kịch bản demo | Khung ở cuối tài liệu này; kịch bản chạy trong `HUONG_DAN_CHAY_DUC.md` | **Đã soạn khung**; chỉ điền kết quả sau khi chạy thật |

## Lệnh theo 8 task

Các lệnh đầy đủ, điều kiện đầu vào, đầu ra kỳ vọng và cách xử lý lỗi nằm trong [HUONG_DAN_CHAY_DUC.md](HUONG_DAN_CHAY_DUC.md). Kịch bản tích hợp đọc-only nằm ở `scripts/check_stage2_integration.sh`. Thứ tự dự kiến:

1. Cài uv/npm, cấu hình `.env`, chạy Neo4j/GDS và `doctor`.
2. `stage2 freeze`, sau đó `stage2 export-huy`.
3. Nạp baseline vào database dự án, không reset database đã có dữ liệu.
4. Crawl luồng tin mới; chỉ bật lịch khi muốn chạy nền hằng ngày.
5. Nhận kết quả Huy, kiểm tra, liên kết/duyệt và nhập tăng dần.
6. Chạy phân tích baseline và sau làm giàu trên đúng snapshot.
7. Tạo embedding/index, xuất/nhập tóm tắt cộng đồng.
8. Chạy API + React, kiểm tra sáu màn hình và demo bằng nguồn có thật.

## Điều kiện xác nhận hoàn thành thực tế

Phần Đức chỉ được đánh dấu hoàn thành sau khi: Neo4j/GDS chạy; snapshot manifest khớp dữ liệu; có báo cáo nhập và phân tích gắn graph version; API Huy thật trả lời/embed đúng hợp đồng; GraphRAG và vector RAG trả ID nguồn hợp lệ; sáu màn hình truy cập được dữ liệu thật; Đức rà soát 15 câu hỏi và hoàn tất phần báo cáo/demo. Các kết quả offline/build không thay thế các điều kiện này.

## Kiểm tra đã chạy ở bàn giao

- `uv run python -m compileall -q crawler app/api main.py tests`: đạt.
- `uv run python -m unittest discover -s tests -v`: **38/38 đạt** trên dữ liệu tạm/fixture.
- `cd app/web && npm ci && npm run build`: đạt; Vite báo một chunk ECharts 541.74 kB chưa nén (184.08 kB gzip), không chặn build; các màn hình được tải theo route.
- JSON schema/example, CLI help, `bash -n scripts/check_stage2_integration.sh`, `docker compose config --quiet` và `git diff --check`: đạt.
- Chưa chạy Docker service, Neo4j/GDS, crawler trên nguồn thật, API Huy, nhập database, phân tích thật hoặc demo; các bước đó chờ Đức chạy theo hướng dẫn.

## Khung báo cáo của Đức

1. **Dữ liệu:** tiêu chí chọn, cutoff, nguồn/tháng, độ dài, bài có ≥2 thực thể, bài chờ duyệt/bị loại, checksum và hạn chế thu thập.
2. **Đồ thị:** schema, số nút/cạnh/bằng chứng trước-sau, tỷ lệ cạnh có bằng chứng, nút cô lập/trùng, số thực thể/quan hệ mới và các quyết định duyệt.
3. **Phân tích mạng:** mô tả mạng, xếp hạng và vai trò, so sánh hai kỳ, Louvain/Leiden/NMI, k-core/cầu nối, world-small với đồ thị tham chiếu; nêu rõ lấy mẫu/seed/đo chính xác.
4. **Ứng dụng:** kiến trúc local, sáu màn hình, bộ lọc, luồng nguồn-bằng-chứng, GraphRAG so với vector; đưa số liệu độ đúng chỉ khi Huy chạy bộ đánh giá.
5. **Hạn chế:** độ phủ/ngày đăng, entity linking chờ duyệt, sai lệch nguồn, giới hạn API/quota, thay đổi model/index.
6. **Phụ lục tái lập:** phiên bản snapshot, graph version, model version, môi trường, lệnh, seed và ngày chạy.

Mỗi bảng/hình cần trỏ tới file trong `data/interim/analysis/snapshots/graph-<version>/`. Không điền số liệu dự kiến hoặc số liệu fixture vào kết quả nghiên cứu.
