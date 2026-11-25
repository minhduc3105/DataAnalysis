# Phân công giai đoạn 2 – Đức và Huy

**Dự án:** Lắng nghe mạng xã hội âm nhạc Việt — VN Music Radar  
**Thời gian thực hiện:** 25/11–05/12/2026  
**Tài liệu gốc:** [Kế hoạch giai đoạn 2](<Kế hoạch giai đoạn 2 – Lắng nghe mạng xã hội âm nhạc Việt.md>)

## 1. Cách chia việc

| Người | Phụ trách chính | Kết quả cuối cùng |
| --- | --- | --- |
| **Huy** | Mô hình: chuẩn bị đầu vào, benchmark, chạy NER/RE, embedding, sinh câu trả lời, đánh giá và đóng gói; train thêm nếu cần | Bộ mô hình chạy cục bộ, API ổn định, kết quả trích xuất và bảng đánh giá |
| **Đức** | Dữ liệu, liên kết thực thể, đồ thị, phân tích mạng, backend và toàn bộ giao diện | Ứng dụng hoàn chỉnh đọc dữ liệu từ đồ thị, giải thích đa bước và hiển thị kết quả phân tích |

**Nguyên tắc:** mỗi người sở hữu trọn phần của mình, có thể chạy và kiểm tra riêng. Không chia giao diện theo màn hình giữa hai người. Hai bên kết nối qua định dạng dữ liệu và API đã thống nhất.

Đức có nhiều đầu việc hơn, nên Huy phụ trách **toàn bộ vòng đời mô hình**, gồm xử lý dữ liệu đầu vào cho model, viết script đánh giá, đóng gói dịch vụ và viết phần báo cáo tương ứng. Không chỉ chạy model rồi chuyển phần xử lý kết quả cho Đức.

## 2. Checklist của Đức

### A. Dữ liệu và thu thập tin — mục 1.1

- [ ] Chốt tập nghiên cứu gồm 5.240 bài sạch đến 21/10/2026; kiểm tra ID, nguồn, URL và ngày xuất bản.
- [ ] Tách tập nghiên cứu cố định khỏi luồng tin mới từ 22/10/2026.
- [ ] Crawl bù báo và xây lịch thu thập báo, video YouTube mới.
- [ ] Làm sạch, chống trùng, ghi nhận lỗi và lý do loại bài.
- [ ] Thống kê số bài theo nguồn/tháng, độ dài và tỷ lệ bài có ít nhất hai thực thể.
- [ ] Xuất dữ liệu, từ điển thực thể, schema và baseline cho Huy.

**Bàn giao:** tập dữ liệu có phiên bản, thống kê tập, script thu thập và gói đầu vào cho mô hình.

### B. Liên kết thực thể và cập nhật đồ thị — mục 1.2–1.4

- [ ] Liên kết thực thể Huy nhận dạng về ID chính thức bằng tên, alias, khóa có sẵn và embedding khi cần.
- [ ] Đưa thực thể chưa liên kết được vào trạng thái chờ duyệt.
- [ ] Kiểm tra quan hệ đúng hướng, đúng kiểu nút và có câu bằng chứng trong văn bản.
- [ ] Nhập kết quả hợp lệ vào Neo4j, lưu nguồn và phiên bản mô hình.
- [ ] Kiểm tra nút trùng, nút cô lập, vi phạm schema và độ phủ bằng chứng.
- [ ] Đánh giá độ chính xác liên kết thực thể, số nút/cạnh mới và thay đổi trước/sau làm giàu.

**Bàn giao:** đồ thị đã làm giàu, quy trình nhập dữ liệu chạy lại được và bảng chất lượng đồ thị.

### C. Phân tích mạng — toàn bộ mục 2.1–2.3

- [ ] Thế giới nhỏ: khoảng cách, đường kính, clustering, transitivity, đồ thị đối chứng, sigma và omega theo phương pháp đã chọn.
- [ ] Xếp hạng: PageRank có trọng số, degree, betweenness, eigenvector, tương quan và top 20.
- [ ] Phân tích theo vai trò và hai giai đoạn 2016–2020, 2021–2026.
- [ ] Cộng đồng: Louvain, Leiden, modularity, NMI và độ ổn định theo seed.
- [ ] Hạt nhân: k-core, nút trung tâm từng cộng đồng và cầu nối giữa cộng đồng.
- [ ] Xuất bảng, biểu đồ và diễn giải vào `data/interim/analysis/`.

**Bàn giao:** bộ kết quả phân tích có phiên bản đồ thị rõ ràng, dùng chung cho báo cáo và ứng dụng.

> Các thuật toán mạng giao cho Đức vì gắn với đồ thị và ứng dụng. Phần mô hình của Huy tập trung vào xử lý ngôn ngữ và embedding.

### D. GraphRAG, backend và giao diện — mục 3.2–3.3

- [ ] Tạo full-text index và vector index từ embedding Huy cung cấp.
- [ ] Liên kết thực thể trong câu hỏi; truy xuất đồ thị tối đa ba bước, lọc thời gian và loại cạnh.
- [ ] Xếp hạng đường đi, gom bằng chứng và chuyển ngữ cảnh sang API trả lời của Huy.
- [ ] Xây truy xuất vector thuần để làm đối chứng với GraphRAG.
- [ ] Xuất dữ liệu cộng đồng cho Huy tóm tắt, lưu kết quả vào hệ thống.
- [ ] Xây FastAPI và chức năng theo dõi, cảnh báo, thống kê xu hướng.
- [ ] Làm đủ sáu màn hình: Bảng tin; Theo dõi và cảnh báo; Xu hướng; Vì sao tin này liên quan; Hỏi đáp; Chân dung mạng.
- [ ] Kiểm tra luồng hoàn chỉnh từ tin đầu vào đến đồ thị, giao diện và câu trả lời có nguồn.

**Bàn giao:** ứng dụng chạy cục bộ, hướng dẫn khởi động, kịch bản demo và dữ liệu demo có thật.

## 3. Checklist của Huy

### A. Môi trường và benchmark — mục 3.1

- [ ] Cài và cấu hình môi trường chạy SLM cục bộ trên máy demo.
- [ ] Benchmark Qwen3-4B và Qwen3-8B theo phạm vi rút gọn của kế hoạch.
- [ ] Đo chất lượng NER/RE, JSON hợp lệ, chất lượng trả lời, tốc độ và bộ nhớ thực tế.
- [ ] Chọn một mô hình chính; ghi rõ phiên bản, lượng tử hóa, prompt và tham số chạy.
- [ ] Chốt mô hình embedding, số chiều và cách xử lý đầu vào sớm để Đức xây chỉ mục.

**Bàn giao:** bảng benchmark, cấu hình có thể chạy lại và mô hình chính hoạt động trên máy demo.

### B. Nhận dạng thực thể và quan hệ — mục 1.2–1.3

- [ ] Chia câu/đoạn từ dữ liệu Đức xuất; giữ liên kết về văn bản và ID gốc.
- [ ] Viết prompt và chạy SLM NER theo tám loại thực thể trong schema.
- [ ] Sinh cặp ứng viên từ thực thể trong cùng câu hoặc hai câu kề nhau.
- [ ] Chạy SLM RE theo 14 loại quan hệ hoặc NONE, kèm câu bằng chứng.
- [ ] Kiểm tra định dạng JSON; xử lý đầu ra sai, retry và ghi log lỗi.
- [ ] Chạy batch, lưu tiến độ để tiếp tục khi bị gián đoạn.
- [ ] Bàn giao kết quả trích xuất đầy đủ, gắn phiên bản mô hình.
- [ ] Train PhoBERT NER/RE nếu rubric bắt buộc hoặc còn thời gian sau phần chính.

**Bàn giao:** script batch, kết quả NER/RE và API `/extract`.

### C. Embedding và sinh văn bản — mục 3.2

- [ ] Đóng gói dịch vụ embedding cho liên kết thực thể và tìm bằng chứng.
- [ ] Tóm tắt cộng đồng từ dữ liệu Đức xuất, giữ tham chiếu nguồn.
- [ ] Sinh câu trả lời từ câu hỏi và bằng chứng Đức gửi.
- [ ] Trả ID nguồn để giao diện hiển thị trích dẫn; xử lý trường hợp thiếu bằng chứng.
- [ ] Thiết lập timeout, thông báo lỗi và hướng dẫn khởi động dịch vụ.

**Bàn giao:** API `/embed`, `/answer`, `/summarize` và dữ liệu mẫu tương ứng.

### D. Đánh giá và báo cáo mô hình — mục 1.4, 3.1–3.2

- [ ] Viết hướng dẫn gán nhãn và script đánh giá NER/RE.
- [ ] Tính P/R/F1 theo loại; so với baseline Đức cung cấp trên cùng tập đánh giá.
- [ ] Tính Cohen's kappa trên phần gán nhãn chung trước khi thống nhất nhãn.
- [ ] Chạy và tổng hợp so sánh GraphRAG với RAG vector trên 30 câu hỏi.
- [ ] Viết phần báo cáo mô hình, benchmark, lỗi điển hình và đánh giá.

**Bàn giao:** bảng số liệu, script đánh giá, kết quả từng mẫu và nội dung báo cáo sẵn để ghép.

## 4. Hợp đồng bàn giao để làm độc lập

### 4.1. Đức → Huy: gói dữ liệu cố định

**Mốc bàn giao đầu tiên: 25/11.**

| Thành phần | Nội dung tối thiểu |
| --- | --- |
| Bài báo sạch | `document_id`, nội dung, nguồn, URL, ngày xuất bản |
| Từ điển thực thể | ID chính thức, tên, loại, alias |
| Schema | Tám loại thực thể, 14 loại quan hệ, hướng và kiểu nút hợp lệ |
| Dữ liệu GĐ1 | Kết quả baseline, 4.256 quyết định đã duyệt và mô tả các trường |
| Tập chạy thử | Khoảng 20 bài để kiểm tra đầu vào/đầu ra |

Huy làm trên bản xuất này, không cần truy cập Neo4j hoặc chờ crawler hoàn thiện. Các đợt bổ sung giữ nguyên cấu trúc và có phiên bản riêng.

### 4.2. Huy → Đức: giao diện mô hình

**Chốt cấu trúc và cung cấp kết quả mẫu ngày 25/11; bản chạy đầu tiên ngày 28/11.**

| API đề xuất | Đầu vào | Đầu ra |
| --- | --- | --- |
| `/extract` | ID và văn bản bài báo | Thực thể, quan hệ, bằng chứng, phiên bản mô hình |
| `/embed` | Danh sách văn bản | Vector, tên mô hình, số chiều |
| `/answer` | Câu hỏi và ngữ cảnh/bằng chứng đã truy xuất | Câu trả lời và ID nguồn |
| `/summarize` | Dữ liệu cộng đồng hoặc nội dung tin | Tóm tắt và ID nguồn |

Có thể thay API bằng hàm Python nếu thuận tiện; cấu trúc đầu vào/đầu ra vẫn phải thống nhất.

**Quy ước bắt buộc:**

1. Huy trả `mention_id` cho thực thể trong từng bài; Đức ánh xạ sang ID chính thức của đồ thị.
2. Quan hệ tham chiếu `mention_id`; bằng chứng phải truy được về văn bản gốc.
3. Kết quả trích xuất có `document_id`, `schema_version`, `model_version`.
4. API trả lời nhận bằng chứng từ Đức, không tự truy vấn Neo4j.
5. Mô hình embedding và số chiều được chốt sớm; nếu đổi phải thông báo vì cần xây lại chỉ mục.
6. Thay đổi cấu trúc phải có phiên bản mới và mẫu dữ liệu đi kèm.

### 4.3. Cách kiểm tra riêng

- **Đức:** dùng kết quả mô hình mẫu đúng cấu trúc để xây và kiểm tra backend, nhập đồ thị, giao diện. Khi có API thật chỉ thay nguồn kết quả.
- **Huy:** dùng bài báo và gói ngữ cảnh mẫu để kiểm tra mô hình, không đợi ứng dụng hoặc truy xuất thật.
- **Cả hai:** dùng dữ liệu mô phỏng trong phát triển; kết quả đánh giá và demo phải ghi rõ nguồn gốc, không trình bày dữ liệu mô phỏng như kết quả mô hình thật.

## 5. Những việc hai người cùng làm

### 5.1. Bộ gold 200 bộ ba

| Người | Mẫu riêng | Mẫu chung | Tổng lượt gán |
| --- | ---: | ---: | ---: |
| Đức | 80 | 40 | 120 |
| Huy | 80 | 40 | 120 |

- Tổng cộng **200 mẫu khác nhau**, trong đó 40 mẫu được cả hai gán độc lập, tương đương chồng lấn 20%.
- Huy chuẩn bị hướng dẫn nhãn và script tính điểm; phân tầng mẫu theo loại quan hệ và nguồn.
- Tính kappa trên 40 mẫu chung **trước khi thảo luận**. Sau đó mới xử lý bất đồng để chốt gold.
- Bộ ba được kiểm tra không đủ để đo toàn bộ recall và NER. Cần tập câu được gán đầy đủ thực thể và quan hệ để tính các chỉ số này.
- Tách dữ liệu chỉnh prompt/chọn cấu hình khỏi tập kiểm thử cuối.

### 5.2. Bộ 30 câu hỏi multi-hop

- Đức viết 15 câu; Huy viết 15 câu.
- Mỗi câu có đáp án mong đợi, đường đi hoặc bằng chứng, và phiên bản dữ liệu dùng để trả lời.
- Đức cung cấp hai cách truy xuất: GraphRAG và vector thuần.
- Huy chạy sinh câu trả lời và tổng hợp độ đúng, độ đúng trích nguồn theo cùng tiêu chí.

### 5.3. Báo cáo và demo

- Đức viết phần dữ liệu, đồ thị, phân tích mạng và ứng dụng; ghép báo cáo, slide và kịch bản demo.
- Huy viết phần mô hình và đánh giá; bàn giao bảng, hình và cấu hình môi trường.
- Hai người đọc chéo một lượt và chạy thử toàn bộ trên máy Huy trước hạn nộp.

## 6. Lịch làm việc và mốc tích hợp

| Thời gian | Đức | Huy | Kết quả cần đạt |
| --- | --- | --- | --- |
| **25/11** | Xuất dữ liệu, schema, baseline; bắt đầu crawl bù | Dựng môi trường model; chốt giao diện, trả mẫu kết quả | Mỗi người đủ đầu vào để làm riêng |
| **26–27/11** | Backend, khung React, liên kết thực thể, nhập đồ thị | NER/RE bản đầu, embedding, script benchmark | Ứng dụng chạy bằng mẫu; mô hình chạy trên tập nhỏ |
| **28–29/11** | Tích hợp trích xuất; phân tích mạng ban đầu; xây truy xuất | Benchmark, chọn SLM, chạy batch; answer/summarize | Một bài đi được từ đầu vào đến giao diện bằng kết quả thật |
| **30/11** | Hoàn thiện bảng tin và đường đi giải thích | API ổn định; kết quả batch bản đầu, bảng benchmark | Kiểm tra tiến độ; chuyển Streamlit nếu React chưa có trang chạy |
| **01–02/12** | Đủ sáu màn hình; GraphRAG/vector; cập nhật phân tích trên snapshot làm giàu | Đánh giá NER/RE; tóm tắt cộng đồng; so sánh hai cách RAG | Chạy đủ luồng trên máy Huy |
| **03–04/12** | Sửa lỗi, kiểm tra đồ thị, ghép báo cáo và demo | Chốt số liệu, phần viết, cấu hình và kết quả dự phòng | Đóng băng tính năng, chạy thử demo |
| **05/12** | Kiểm tra và nộp | Kiểm tra máy demo, hỗ trợ nộp | Không thêm tính năng mới |

**Chỉ cần ba nhóm phối hợp chính:** chốt hợp đồng dữ liệu; xử lý nhãn bất đồng; tích hợp ứng dụng. Không đợi hoàn thành toàn bộ từng phần mới chạy chung.

## 7. Ưu tiên và giới hạn phạm vi

### Phần cần hoàn thành trước

- Baseline GĐ1 và SLM NER/RE.
- Benchmark hai SLM theo phạm vi rút gọn.
- Liên kết thực thể, bằng chứng và đồ thị đã làm giàu.
- Đủ ba mục phân tích mạng.
- GraphRAG, đối chứng RAG vector và đánh giá.
- Sáu màn hình ở mức chức năng; ưu tiên bảng tin, giải thích đa bước và hỏi đáp có nguồn.

### Chỉ làm thêm khi phần chính ổn định

- Train PhoBERT NER/RE.
- Benchmark Vistral.
- Gán cảm xúc tin.
- Spotify định kỳ.
- Trang trí và hiệu ứng giao diện nâng cao.

> **Cần đối chiếu rubric chính thức:** tài liệu gốc chưa thống nhất giữa hai hay ba SLM, và việc PhoBERT là bắt buộc hay tùy chọn. Phân công này theo phần “Phạm vi rút gọn cho hạn nộp”. Nếu rubric bắt buộc train mô hình riêng hoặc benchmark ba SLM, Huy đưa phần đó trở lại nhóm bắt buộc.

## 8. Tiêu chí hoàn thành

| Người | Hoàn thành khi |
| --- | --- |
| **Huy** | Có cấu hình mô hình chạy lại được; API đúng hợp đồng; kết quả batch; bảng đánh giá có dữ liệu đối chiếu; phần báo cáo mô hình hoàn chỉnh |
| **Đức** | Có pipeline dữ liệu và nhập đồ thị; kết quả phân tích mạng; ứng dụng đủ chức năng chạy với API thật; báo cáo và demo được ghép hoàn chỉnh |
| **Cả nhóm** | Chạy thử thành công trên máy Huy; câu trả lời và đường đi có bằng chứng; phân biệt tập nghiên cứu với tin mới; kết quả được gắn đúng phiên bản dữ liệu |
