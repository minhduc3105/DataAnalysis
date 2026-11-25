# Kế hoạch giai đoạn 2 – Lắng nghe mạng xã hội âm nhạc Việt

Nov 23, 2026 · @Quoc Huy Dang

Giai đoạn 2 chiếm 8 điểm: làm giàu đồ thị bằng văn bản (2đ), phân tích mạng (1.5đ) và ứng dụng lắng nghe mạng xã hội dùng đồ thị tri thức (4.5đ). Nhóm xây một hệ thống theo dõi tin mới về ca sĩ, nhạc sĩ, công ty, dựa trên đồ thị GĐ1 (12.436 nút, 35.096 cạnh) và 5.240 bài báo đã làm sạch; mọi phần đều đổ về một ứng dụng demo.

## Phạm vi rút gọn cho hạn nộp

Hạn nộp là Dec 5, 2026, còn 12 ngày tính từ 23/11. Mỗi phần chỉ làm một cách chính. Một SLM dùng chung cho NER, quan hệ và hỏi đáp, nên một lần benchmark phục vụ cả ba tiêu chí.

| Phần | Giữ | Cắt hoặc chỉ làm nếu còn thời gian |
| --- | --- | --- |
| Tập làm giàu | 5.240 bài + crawl bù báo từ 22/10 đến nay, bắt đầu ngay 23/11; video mới YouTube | Spotify định kỳ |
| NER và quan hệ | SLM few-shot + liên kết từ điển; baseline luật GĐ1 | PhoBERT gán nhãn yếu, PhoBERT phân loại quan hệ |
| Chọn SLM | Qwen3-8B so với Qwen3-4B trên 100 câu gán tay | Vistral-7B |
| Bộ gold | 200 bộ ba, chồng lấn 20% để tính kappa | 300–500 bộ ba |
| Phân tích mạng | Giữ đủ 2.1–2.3 | – |
| GraphRAG | Truy xuất ≤ 3 bước + tóm tắt cộng đồng; so với RAG vector trên 30 câu | 50 câu |
| Ứng dụng | 6 màn hình bằng React; mốc lùi Streamlit ngày 30/11 | Gán cảm xúc tin |

## Đề bài và hiện trạng

Khoảng một nửa số điểm đã có nền từ GĐ1. Phần thiếu lớn nhất là các mô hình NER/RE dạng học máy, SLM chạy cục bộ và toàn bộ ứng dụng (3 điểm).

| Mục | Điểm | Đã có từ GĐ1 | Cần làm thêm |
| --- | --- | --- | --- |
| 1.1 Tập dữ liệu làm giàu | 0.5 | 5.240 bài báo sạch (Đức); mô tả \~30k video YouTube; credit Spotify | Chốt tập, thống kê tập; thêm luồng thu thập định kỳ sau mốc 21/10/2026 |
| 1.2 Nhận dạng thực thể | 0.5 | Luật + từ điển (`extract.py`); liên kết thực thể báo chí theo từ điển | Mô hình học máy (PhoBERT giám sát yếu) + SLM tìm thực thể mới; liên kết về đồ thị |
| 1.3 Nhận dạng quan hệ | 0.5 | Luật tiêu đề/credit; báo chí: tín hiệu + LLM rà soát qua OpenRouter; 4.256 quyết định đã duyệt | Mô hình quan hệ chạy SLM ≤9B cục bộ; bộ phân loại học từ 4.256 quyết định |
| 1.4 Đánh giá đồ thị | 0.5 | Script soát entity, `neo4j check`, precision mẫu \~93% trên 50 cạnh | Bộ gold 200 bộ ba, P/R/F1 theo loại, kappa giữa 2 người, chỉ số nhất quán |
| 2.1 Thế giới nhỏ | 0.5 | Chưa có | L, C, so với đồ thị ngẫu nhiên cùng n, m; hệ số σ, ω |
| 2.2 Xếp hạng nút | 0.5 | PageRank, Betweenness, Degree (`analyze`) | PageRank có trọng số; so sánh các thước đo; xếp theo vai trò và thời kỳ |
| 2.3 Cộng đồng và hạt nhân | 0.5 | Louvain: 35 cộng đồng, modularity 0.64 (số liệu 10/11, cần chạy lại) | Leiden để đối chiếu; k-core; hạt nhân từng cộng đồng |
| 3.1 SLM ≤9B | 1 | Chưa có | Benchmark 3 mô hình, chọn 1, chạy Ollama trên RTX 4050 6 GB |
| 3.2 Đồ thị tri thức + GraphRAG | 0.5 | Đồ thị trên Neo4j có Document/Evidence | Vector index, truy xuất đồ thị con k bước, tóm tắt cộng đồng |
| 3.3 Ứng dụng lắng nghe + multi-hop | 3 | Chỉ có `viewer.html` tĩnh | Web app: bảng tin, theo dõi chủ đề, giải thích đa bước, hỏi đáp, số liệu SNA |

Tổng 8 điểm. 2 điểm còn lại của môn (báo cáo, thuyết trình) chưa có trong đề này.

## Kiến trúc hệ thống

&#91;embedded content: kiến trúc hệ thống · 5 tầng\]

Tầng làm giàu dùng chung cho tập nghiên cứu và luồng tin mới; ứng dụng chỉ đọc từ đồ thị, không đọc thẳng nguồn tin.

## Hạng mục 1 – Làm giàu dữ liệu (2 điểm)

Báo chí là tập làm giàu chính. NER và quan hệ đều có một mô hình học máy nhỏ (PhoBERT) và một mô hình SLM, so với baseline luật + từ điển của GĐ1 trên cùng bộ gold.

### 1.1 Tập dữ liệu làm giàu (0.5đ)

- **Tập nghiên cứu (đóng băng đến 21/10/2026):** 5.240 bài báo đã làm sạch từ `seeds/web_sources.csv`; mô tả video YouTube và credit Spotify là nguồn có cấu trúc. Dùng cho đánh giá và phân tích mạng.
- **Luồng tin mới (cho ứng dụng):** chạy mỗi ngày sau mốc chốt.
  - Báo: dùng lại `web discover/crawl` với `--from` = ngày chạy trước, ưu tiên RSS/sitemap.
  - YouTube: video mới của \~280 kênh seed qua playlist uploads, khoảng 300 đơn vị quota/ngày (hạn mức 10.000).
  - Spotify: bản phát hành mới mỗi tuần, có `--max-calls` vì app dễ bị khóa 18–24 giờ.
  - TikTok/Facebook: không có API hợp lệ nên không làm (giữ quyết định GĐ1).
- Tin mới đổ vào một lớp riêng có mốc thời gian, không làm đổi số liệu phân tích của tập nghiên cứu.
- Báo cáo cần: số bài theo nguồn và theo tháng, độ dài trung bình, tỉ lệ bài có ≥2 thực thể, lý do loại bài.

### 1.2 Mô hình nhận dạng thực thể (0.5đ)

Nhãn theo schema: Person, Group, Song, Album, Company, Show, Event, Brand.

1. **Baseline:** luật + từ điển GĐ1 (12k thực thể và alias).
2. **PhoBERT-base (135M) gán nhãn BIO, giám sát yếu (chỉ làm nếu còn thời gian):** khớp từ điển vào câu báo để tạo nhãn tự động; sửa tay 300–500 câu làm tập dev/test. Huấn luyện được trên RTX 4050.
3. **SLM few-shot:** trả JSON `{text, type}`, dùng để bắt tên chưa có trong từ điển.
4. **Liên kết thực thể:** chuẩn hóa tên, alias và `song_key` sẵn có; không khớp thì so embedding bge-m3 theo ngưỡng; vẫn không khớp thì tạo nút mới ở trạng thái chờ duyệt.

Báo cáo P/R/F1 theo loại cho cả 3 cách và độ chính xác liên kết thực thể.

### 1.3 Mô hình nhận dạng quan hệ (0.5đ)

1. **Ứng viên:** cặp thực thể đã liên kết trong cùng câu hoặc hai câu kề nhau.
2. **SLM phân loại:** (e1, e2, câu) → một trong 14 loại quan hệ hoặc NONE, kèm câu trích bằng chứng; JSON ràng buộc hướng và kiểu nút. Thay bước rà soát OpenRouter của GĐ1 để đúng yêu cầu ≤9B.
3. **PhoBERT phân loại quan hệ (chỉ làm nếu còn thời gian):** huấn luyện từ 4.256 quyết định accepted/rejected đã có cộng nhãn do SLM sinh; nhanh, dùng cho luồng hằng ngày.
4. **Luật hậu kiểm:** đúng hướng và kiểu nút; không tạo hợp tác chỉ vì cùng bài báo; câu trích phải có thật trong văn bản.

Mỗi cạnh mới mang `confidence`, `model_version` và bằng chứng; dưới ngưỡng thì vào hàng chờ duyệt.

### 1.4 Đánh giá chất lượng đồ thị (0.5đ)

- **Bộ gold:** 200 bộ ba lấy mẫu phân tầng theo loại quan hệ và nguồn; Huy và Đức gán độc lập, chồng lấn 20% để tính Cohen's kappa.
- **Độ đúng:** precision theo loại cạnh (mục tiêu ≥90% như GĐ1), recall trên tập câu gán tay, F1 NER theo loại, độ chính xác liên kết.
- **Độ nhất quán:** tỉ lệ vi phạm schema, nút trùng (script soát entity), nút cô lập, 100% cạnh có bằng chứng, độ phủ so với credit Spotify.
- **Giá trị làm giàu:** số nút/cạnh mới từ văn bản; PageRank và cộng đồng thay đổi thế nào trước và sau làm giàu.

## Hạng mục 2 – Phân tích mạng xã hội (1.5 điểm)

Mạng phân tích chính là mạng hợp tác Person/Group (cạnh `COLLABORATED_WITH`, trọng số = số bài chung), xét trên thành phần liên thông lớn nhất; các chỉ số chính báo thêm cho đồ thị tri thức đầy đủ. Mọi kết quả xuất ra `data/interim/analysis/` và hiển thị trên ứng dụng.

### 2.1 Chứng minh thế giới nhỏ (0.5đ)

- Tính L (khoảng cách ngắn nhất trung bình), đường kính, phân phối khoảng cách, C (hệ số gom cụm trung bình và transitivity).
- So với 20 đồ thị ngẫu nhiên Erdős–Rényi và 20 đồ thị giữ phân phối bậc, cùng n và m. Kết luận thế giới nhỏ khi σ = (C/Cᵣ)/(L/Lᵣ) > 1 và ω gần 0.
- Công cụ: NetworkX với mạng \~1.400 nút (vài giây); GDS cho đồ thị tri thức lớn.
- Hình cho báo cáo: histogram khoảng cách, một ví dụ đường đi giữa hai nghệ sĩ ở hai dòng nhạc khác nhau.

### 2.2 Xếp hạng nút (0.5đ)

- PageRank có trọng số trên mạng hợp tác; PageRank trên đồ thị tri thức để xếp hạng công ty và bài hát.
- So với degree, betweenness, eigenvector bằng tương quan Spearman; top 20 theo từng thước đo.
- Xếp riêng theo vai trò (ca sĩ, nhạc sĩ, producer) và theo hai giai đoạn 2016–2020 và 2021–2026.

### 2.3 Cộng đồng và hạt nhân (0.5đ)

- Louvain (đã có) và Leiden (GDS): so modularity, NMI giữa hai cách chia, độ ổn định qua 10 lần chạy khác seed.
- Hạt nhân toàn mạng: phân rã k-core (`gds.kcore`), lấy lõi k lớn nhất.
- Hạt nhân từng cộng đồng: nút có bậc nội bộ và PageRank cao nhất; đặt tên cộng đồng theo dòng nhạc hoặc công ty chiếm đa số.
- Cầu nối giữa các cộng đồng (GĐ1: Nguyễn Văn Chung, Karik, MASEW, Bùi Công Nam) được kiểm tra lại trên đồ thị mới.

## Hạng mục 3 – Ứng dụng lắng nghe mạng xã hội (4.5 điểm)

Ứng dụng (tên tạm: **VN Music Radar**) theo dõi tin mới về nghệ sĩ, công ty và cộng đồng. Nó giải thích mỗi tin liên quan đến chủ đề đang theo dõi bằng đường đi nhiều bước trên đồ thị, kèm bằng chứng. Điểm nặng nhất (3đ) nằm ở multi-hop và giao diện, nên khung giao diện phải bắt đầu từ 26/11.

### 3.1 Chọn mô hình ngôn ngữ nhỏ ≤9B (1đ)

Máy có RTX 4050 6 GB VRAM nên chạy bản lượng tử 4-bit qua Ollama. Benchmark Qwen3-8B và Qwen3-4B trên bộ gold rồi chọn một mô hình chính; Vistral chỉ thử nếu còn thời gian. Bảng so sánh này chính là nội dung của tiêu chí 1 điểm.

| Ứng viên | Tham số | VRAM 4-bit (ước lượng) | Lý do thử |
| --- | --- | --- | --- |
| Qwen3-8B | \~8B | \~5 GB | Tiếng Việt tốt, tuân thủ JSON, có chế độ suy luận |
| Qwen3-4B | \~4B | \~3 GB | Dư VRAM cho ngữ cảnh dài, nhanh khi xử lý hàng loạt |
| Vistral-7B-Chat | \~7B | \~4.5 GB | Tinh chỉnh riêng cho tiếng Việt |

- Tiêu chí so: F1 NER, F1 quan hệ, tỉ lệ JSON hợp lệ, độ đúng trả lời trên 30 câu multi-hop, token/giây, VRAM.
- Embedding: bge-m3 (568M, đa ngôn ngữ) cho liên kết thực thể và tìm bằng chứng.
- SLM được dùng cho: NER và quan hệ của tin mới, tóm tắt tin, gán cảm xúc, tóm tắt cộng đồng, sinh câu trả lời có trích nguồn.
- Kiểm tra lại phiên bản mới nhất của từng họ mô hình trước khi benchmark.

### 3.2 Đồ thị tri thức và GraphRAG (0.5đ)

1. **Đồ thị tri thức:** Neo4j gồm nút thực thể, Document/Evidence (đã có) và thuộc tính phân tích (`pagerank`, `community`, `core`).
2. **Chỉ mục:** vector index trên embedding câu bằng chứng và mô tả nút; full-text index trên tên và alias.
3. **Truy xuất:** liên kết thực thể trong câu hỏi, mở rộng đồ thị con tối đa 3 bước có lọc loại cạnh và thời gian, xếp hạng đường đi theo PageRank và độ mới, đính kèm câu bằng chứng.
4. **Tóm tắt cộng đồng kiểu GraphRAG:** SLM viết báo cáo cho mỗi cộng đồng Louvain, dùng cho câu hỏi tổng quát.
5. **Đánh giá:** so RAG vector thuần với GraphRAG trên 30 câu multi-hop, theo độ đúng và trích nguồn đúng.

### 3.3 Ứng dụng lắng nghe với suy luận multi-hop (3đ)

| Màn hình | Người dùng thấy gì | Phần đồ thị phía sau |
| --- | --- | --- |
| Bảng tin | Tin mới nhất theo chủ đề đang theo dõi, lọc nguồn và thời gian; thực thể và quan hệ mới trong từng tin | NER, liên kết, quan hệ trên luồng tin mới |
| Theo dõi và cảnh báo | Chọn nghệ sĩ, công ty, cộng đồng, show; cảnh báo khi có bài mới, hợp tác mới, phát hành mới, tranh chấp, đột biến lượng nhắc | Theo dõi cả hàng xóm 1–2 bước; đột biến = z-score so với 4 tuần trước |
| Xu hướng | Nghệ sĩ, bài hát, cộng đồng đang lên; chủ đề nóng; cảm xúc tin | Số nhắc theo ngày, gộp theo cộng đồng |
| Vì sao tin này liên quan? | Đường đi từ thực thể trong tin đến chủ đề đang theo dõi, mỗi bước kèm bằng chứng | Đường đi ngắn nhất có trọng số, tối đa 3 bước |
| Hỏi đáp | Câu trả lời kèm đồ thị con và nguồn | GraphRAG (3.2) |
| Chân dung mạng | Thế giới nhỏ, bảng PageRank, cộng đồng, hạt nhân; đồ thị tương tác tô màu cộng đồng, cạnh mới nổi bật | Kết quả hạng mục 2 |

Câu hỏi multi-hop mẫu (mở rộng thành bộ 30 câu đánh giá):

- “Tuần này có tin gì về những người từng hợp tác với Hoàng Dũng?” – 2 bước cộng lọc thời gian.
- “Producer nào làm việc cho nghệ sĩ của công ty X đang có tin mới?” – 3 bước.
- “Thí sinh Em Xinh Say Hi nào vừa ra bài cùng thành viên Anh Trai Say Hi?” – 3 bước qua Show và Song.
- “Tranh chấp mới nhất trong cộng đồng của Karik ảnh hưởng tới những ai?” – cộng đồng cộng 1–2 bước.

Công nghệ: backend FastAPI (dùng lại `crawler/`), Neo4j, Ollama; frontend React + Vite với Cytoscape.js hoặc Sigma.js cho đồ thị và ECharts cho biểu đồ; lập lịch thu thập bằng APScheduler. Phương án lùi nếu trễ: Streamlit, nhanh hơn nhưng khó đạt tiêu chí giao diện đẹp.

## Phân công

Phân công theo phần mỗi người đã làm ở GĐ1. Đức giữ văn bản báo chí và các mô hình trích xuất. Huy giữ đồ thị, phân tích mạng và backend ứng dụng. Giao diện chia theo màn hình.

| Việc | Chính | Hỗ trợ |
| --- | --- | --- |
| 1.1 Luồng báo chí hằng ngày + thống kê tập làm giàu | Đức | Huy |
| 1.1 Luồng YouTube/Spotify định kỳ | Huy | – |
| 1.2 PhoBERT NER giám sát yếu + SLM tìm thực thể mới | Đức | Huy |
| 1.2 Liên kết thực thể và gộp vào đồ thị tổng | Huy | Đức |
| 1.3 Mô hình quan hệ (SLM + PhoBERT từ 4.256 quyết định) | Đức | Huy |
| 1.4 Gán nhãn bộ gold (chồng lấn 20%) | Huy + Đức | – |
| 1.4 Chỉ số nhất quán và báo cáo đánh giá | Huy | Đức |
| 2.1–2.3 Thế giới nhỏ, PageRank, cộng đồng, k-core | Huy | Đức đọc chéo diễn giải |
| 3.1 Benchmark và chọn SLM | Đức | Huy |
| 3.2 GraphRAG: chỉ mục, truy xuất, tóm tắt cộng đồng | Huy | Đức |
| 3.3 Backend API + truy vấn multi-hop | Huy | – |
| 3.3 Giao diện: Bảng tin, Xu hướng, Theo dõi | Đức | – |
| 3.3 Giao diện: Chân dung mạng, Vì sao liên quan, Hỏi đáp | Huy | – |
| Báo cáo và slide demo | Huy + Đức (ai làm phần nào viết phần đó) | Đọc chéo |

Nếu nhóm có thêm người, giao riêng giao diện và bộ gold cho người đó.

## Lộ trình

&#91;embedded content: lộ trình 23/11–05/12 · 3 điểm kiểm tra\]

Mỗi điểm kiểm tra là một buổi họp ngắn; đến 30/11 frontend chưa có trang nào chạy thì chuyển giao diện sang Streamlit để giữ đủ chức năng.

## Rủi ro và phương án dự phòng

| Rủi ro | Ảnh hưởng | Phương án |
| --- | --- | --- |
| SLM 8B 4-bit chậm hoặc tràn VRAM 6 GB | Xử lý 5.240 bài kéo dài, ứng dụng trả lời chậm | Chỉ gửi câu có ≥2 thực thể; chạy hàng loạt qua đêm; nếu vẫn chậm, chọn bản 4B cùng họ |
| SLM bịa quan hệ hoặc câu trích | Giảm precision dưới 90% | Bắt buộc trích câu, kiểm tra câu có trong văn bản, ràng buộc schema, ngưỡng confidence |
| Hết quota YouTube, Spotify khóa 18–24 giờ | Luồng tin mới đứt quãng khi demo | Giới hạn `--max-calls`; Spotify chạy theo tuần; demo dùng dữ liệu đã thu sẵn |
| Báo chặn crawler | Thiếu tin mới | Ưu tiên RSS, giãn nhịp, bỏ nguồn lỗi |
| ID giữa đồ thị YouTube và đồ thị báo chí lệch nhau (như HYPERFOCUS) | Mất cạnh khi gộp | Dùng chung `id_registry.csv`; kiểm log “Bỏ qua … cạnh” sau mỗi lần build |
| Giao diện tốn thời gian hơn dự kiến | Mất điểm phần 3đ | Dựng khung UI từ 26/11 với dữ liệu giả lập từ API thật; lùi về Streamlit nếu 30/11 vẫn chưa có trang nào chạy |

## Câu hỏi cần chốt

- [x] Hạn nộp: 05/12/2026, còn 12 ngày; lộ trình đã rút gọn.
- [x] Wikipedia: không được dùng, kể cả để đối chiếu; tập làm giàu chỉ gồm báo chí, YouTube và Spotify.
- [x] Demo: chạy trên máy cá nhân của Huy (RTX 4050); Ollama, Neo4j và ứng dụng đều chạy cục bộ, không cần deploy.
- [ ] Giảng viên có chỉ định mô hình SLM hay định dạng báo cáo không?
- [ ] Bộ 30 câu multi-hop: mỗi người viết 15 câu kèm đáp án trước khi làm GraphRAG.
