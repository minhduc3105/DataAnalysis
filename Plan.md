# KẾ HOẠCH THỰC HIỆN ĐỒ ÁN THEO TỪNG BƯỚC

**Đề tài 23: Xây dựng và phân tích mạng lưới Ca sĩ, Nhạc sĩ và Công ty Giải trí Việt Nam bằng kỹ thuật xử lý ngôn ngữ tự nhiên.**

Tài liệu này hướng dẫn cần làm gì, làm như thế nào và kết quả cần có ở từng bước. Đây là kế hoạch triển khai, không chứa code; các số lượng dự kiến chưa phải kết quả thực tế.

## 1. Hiểu đơn giản đề tài

Nhóm cần đọc thông tin từ báo điện tử và các kênh chính thức, tìm những đối tượng trong ngành âm nhạc cùng mối quan hệ giữa họ, rồi lưu thành một mạng lưới để phân tích.

Ví dụ giả định:

> “Ca sĩ A thể hiện bài hát X do nhạc sĩ B sáng tác, được công ty C phát hành.”

Từ câu trên, cần lấy được:

- Bốn đối tượng: A, B, X và C.
- Ba quan hệ: A trình bày X; B sáng tác X; X được C phát hành.
- Bằng chứng: câu văn gốc, URL, tên nguồn và ngày đăng.

Mỗi đối tượng là một **nút (node)**. Mỗi quan hệ là một **cạnh (edge)**. **NLP** là xử lý ngôn ngữ tự nhiên, dùng để tìm tên và quan hệ trong văn bản. **Neo4j** là cơ sở dữ liệu lưu mạng lưới này.

Sau đó nhóm trả lời các câu hỏi như: nghệ sĩ nào có nhiều cộng sự, có những cộng đồng hợp tác nào, công ty nào phát hành nhiều sản phẩm trong dữ liệu.

**Thứ tự thực hiện:** Chốt phạm vi → thiết kế dữ liệu → chọn nguồn → lấy mẫu nhỏ → làm sạch → tạo đáp án mẫu → nhận diện và chuẩn hóa tên → lấy quan hệ → đánh giá → mở rộng → đưa vào Neo4j → phân tích → báo cáo và demo.

## 2. Các yêu cầu cần giữ

Các yêu cầu dưới đây được giữ theo bản kế hoạch ban đầu, cần đối chiếu với đề gốc trước khi triển khai.

| Nội dung | Mục tiêu | Cách hiểu |
|---|---|---|
| Số nút | Ít nhất 2.000 | Đối tượng khác nhau sau khi gộp trùng |
| Số cạnh | Ít nhất 5.000 | Quan hệ có bằng chứng, không đếm trùng |
| Loại quan hệ | Ít nhất 10 | Có dữ liệu thật, không chỉ khai báo tên loại |
| Độ chính xác | Trên 90% | Đề xuất đo precision của bộ ba quan hệ; cần thống nhất với giảng viên |
| Cơ sở dữ liệu | Neo4j | Lưu, truy vấn và trực quan hóa mạng |
| Phân tích | Thống kê và thuật toán mạng | Có kết quả kèm giải thích |
| Báo cáo | Ít nhất 10 trang | Dự kiến 12–15 trang |
| Bàn giao | Dữ liệu, mã nguồn, hướng dẫn và demo | Mã nguồn sẽ thực hiện ở giai đoạn triển khai, không viết trong bản kế hoạch này |

**Điểm cần xác nhận:** Bản cũ có nhắc cách ghi “2000 nghìn nút”. Tạm lập kế hoạch theo 2.000 nút. Nếu đề thật sự yêu cầu 2 triệu nút thì cần lập lại phương án thời gian và tài nguyên.

**Phạm vi:** Âm nhạc Việt Nam, ưu tiên 2018–2026 nhưng chỉ thu thập nội dung đã xuất bản đến ngày chốt dữ liệu; bổ sung trước 2018 nếu cần. Không sử dụng Wikipedia hoặc Wikidata để thu thập hay bổ sung thực thể.

## Bước 1. Chốt phạm vi và câu hỏi phân tích

**Trạng thái:** Hoàn thành. Phạm vi và năm câu hỏi nghiên cứu dưới đây đã được nhóm thống nhất.

**Đề tài:** Xây dựng và phân tích mạng lưới hợp tác trong ngành âm nhạc Việt Nam giai đoạn 2016–2026 bằng kỹ thuật xử lý ngôn ngữ tự nhiên.

**Thành viên và thời hạn:** Nhóm gồm 2 thành viên; hạn nộp đồ án là 05/11/2026. Mốc chốt dữ liệu dự kiến là 22/10/2026. Chỉ đưa vào phạm vi các nội dung xuất bản đến mốc này; lưu riêng ngày thu thập thực tế.

**Phạm vi dữ liệu:** Toàn ngành âm nhạc Việt Nam trong giai đoạn nghiên cứu, bao phủ sáu nhóm: V-pop/Nhạc trẻ; Rap/Hip-hop; Indie/Alternative; Rock/Band; Dân gian đương đại/Bolero/Trữ tình; EDM/Electronic. Nguồn gồm báo chí, website chính thức và tài khoản mạng xã hội chính thức đã xác minh. Không sử dụng Wikipedia hoặc Wikidata. Khởi tạo khoảng 180 thực thể từ nghệ sĩ, công ty và chương trình, sau đó mở rộng có kiểm soát dựa trên bằng chứng.

**Mục tiêu và tiêu chí:** Tối thiểu 2.000 node (cần đối chiếu đề gốc để xác nhận cách ghi), 5.000 edge có ý nghĩa, ít nhất 10 loại quan hệ thực tế và độ chính xác trên 90% được đánh giá độc lập. Báo cáo tối thiểu 10 trang; bàn giao mã nguồn GitHub, thống kê và phân tích mạng. Mỗi cạnh phải truy được về nguồn chứng cứ. Không tạo quan hệ chỉ vì hai thực thể cùng xuất hiện trong một bài viết; không dùng dữ liệu giả để đạt chỉ tiêu.

**Kiến trúc:** Knowledge Graph lưu nghệ sĩ, bài hát, album, công ty, nhóm nhạc, chương trình, sự kiện và thương hiệu. Artist Collaboration Network được suy ra từ credit tác phẩm chung đã kiểm chứng. Dùng Neo4j để lưu trữ và phân tích graph.

**Câu hỏi nghiên cứu:**

1. RQ1: Có những cộng đồng hợp tác âm nhạc nào tại Việt Nam?
2. RQ2: Nghệ sĩ, nhạc sĩ hoặc producer nào là cầu nối giữa các cộng đồng?
3. RQ3: Mạng hợp tác và cấu trúc cộng đồng thay đổi thế nào từ 2016–2026?
4. RQ4: Các cộng đồng có xu hướng hoạt động và hợp tác đặc trưng gì?
5. RQ5: Các cộng đồng đóng góp những gì vào hoạt động sản xuất tác phẩm, hợp tác và kết nối trong ngành âm nhạc?

**Phần nâng cao nếu còn thời gian:** Dashboard tương tác, trực quan hóa sự phát triển mạng theo thời gian và so sánh sâu sáu nhóm âm nhạc. Ưu tiên hoàn thành pipeline tái tạo được, dữ liệu có bằng chứng và các phân tích cốt lõi trước.

**Đầu ra:** Phạm vi, thời hạn, nhóm âm nhạc, nguồn dữ liệu, kiến trúc, tiêu chí hoàn thành và năm câu hỏi nghiên cứu đã được chốt.

**Hoàn thành khi:** Đạt được sự thống nhất trên; bước tiếp theo là thiết kế graph schema và cấu trúc dữ liệu thu thập ở Bước 2.

## Bước 2. Thiết kế dữ liệu trước khi thu thập

**Mục đích:** Thống nhất cách lưu đối tượng, quan hệ và bằng chứng.

### 2.1. Các loại nút

| Loại | Đại diện cho | Số lượng tham khảo |
|---|---|---:|
| Person | Ca sĩ, rapper, nhạc sĩ, producer | 650 |
| Song | Bài hát | 1.250 |
| Album | Album, EP | 200 |
| Company | Công ty giải trí, hãng đĩa | 130 |
| Show | Chương trình âm nhạc, gameshow | 70 |
| Event | Concert, lễ trao giải, sự kiện | 160 |
| Group | Nhóm nhạc | 100 |
| Brand | Thương hiệu hợp tác | 120 |
| **Tổng** | | **2.680** |

Các con số là phân bổ dự kiến, có thể điều chỉnh theo dữ liệu. Một người vừa hát vừa sáng tác vẫn chỉ có một nút Person với nhiều vai trò.

Mỗi nút cần: ID duy nhất, tên chuẩn, loại, tên khác nếu có và nguồn xác minh. Thống nhất cách phân biệt chương trình theo mùa, sự kiện theo năm và bài hát với phiên bản biểu diễn để tránh gộp nhầm.

### 2.2. Các loại quan hệ

| Quan hệ | Hướng nối | Ý nghĩa |
|---|---|---|
| COMPOSED | Person → Song | Sáng tác bài hát |
| PERFORMED | Person → Song | Trình bày bài hát |
| PRODUCED | Person → Song | Sản xuất âm nhạc |
| FEATURED_ON | Person → Song | Nghệ sĩ khách mời |
| RELEASED_BY | Song → Company | Công ty phát hành bài hát |
| TRACK_OF | Song → Album | Bài hát thuộc album |
| MEMBER_OF | Person → Group | Thành viên nhóm nhạc |
| MANAGED_BY | Person → Company | Công ty quản lý nghệ sĩ |
| CONTESTANT_ON | Person → Show | Thí sinh chương trình/mùa |
| JUDGE_ON | Person → Show | Giám khảo hoặc huấn luyện viên; ghi rõ vai trò |
| PERFORMED_AT | Person → Event | Đã biểu diễn tại sự kiện |
| AMBASSADOR_OF | Person → Brand | Đại sứ thương hiệu |
| ORGANIZED_BY | Event → Company | Công ty tổ chức sự kiện |
| COLLABORATED_WITH | Person ↔ Person | Hợp tác qua sản phẩm chung đã xác minh |

Thử trước 4–6 loại dễ có bằng chứng, sau đó mở rộng để có ít nhất 10 loại thực tế. Mục tiêu đầy đủ là 12–14 loại nếu dữ liệu đáp ứng.

Quan hệ hợp tác là quan hệ dẫn xuất từ credit cùng sản phẩm, tức thông tin xác nhận những người tham gia sản phẩm đó. Không suy ra hợp tác chỉ vì cùng bài báo, chương trình hay sự kiện. Thống kê riêng cạnh trực tiếp và cạnh dẫn xuất; chốt với giảng viên cách tính cạnh dẫn xuất vào chỉ tiêu.

### 2.3. Chuẩn bị bốn bảng dữ liệu

Mỗi bảng lưu một loại thông tin riêng. Các trường **Bắt buộc** cần có cho mỗi dòng; trường **Tùy chọn** chỉ điền khi nguồn cung cấp hoặc nhóm cần dùng. Trường chưa biết để trống, không tự suy đoán.

#### Bảng Tài liệu (`Document`)

Mỗi dòng đại diện cho một bài báo hoặc bài đăng đã thu thập.

| Trường | Bắt buộc? | Ý nghĩa |
|---|---|---|
| `document_id` | Có | ID duy nhất, ví dụ `DOC_0001` |
| `url` | Có | Đường dẫn tài liệu gốc |
| `source_name` | Có | Tên báo, website hoặc tài khoản đăng |
| `source_type` | Có | Báo chí, website tổ chức, mạng xã hội... |
| `title` | Có | Tiêu đề bài viết hoặc nội dung nhận diện bài đăng |
| `published_at` | Có nếu nguồn cung cấp | Ngày đăng; để trống nếu không xác định được |
| `collected_at` | Có | Ngày nhóm thu thập tài liệu |
| `content` | Có | Nội dung văn bản dùng để phân tích |
| `collection_method` | Có | RSS, API, lấy thủ công hoặc phương thức được phép khác |
| `document_status` | Có | Hợp lệ, trùng lặp, loại bỏ hoặc cần kiểm tra |
| `author` | Tùy chọn | Tác giả bài viết |
| `account_verified` | Tùy chọn | Có/không/không rõ, áp dụng với tài khoản mạng xã hội |
| `exclude_reason` | Tùy chọn | Lý do loại tài liệu nếu không sử dụng |

Nếu điều kiện nguồn không cho phép chia sẻ toàn văn, chỉ lưu metadata và đoạn trích cần thiết theo quy định áp dụng.

#### Bảng Thực thể (`Entity`)

Mỗi dòng đại diện cho một đối tượng riêng đã được chuẩn hóa.

| Trường | Bắt buộc? | Ý nghĩa |
|---|---|---|
| `entity_id` | Có | ID duy nhất, ví dụ `PER_0001`, `SON_0001` |
| `entity_type` | Có | Person, Song, Album, Company, Show, Event, Group hoặc Brand |
| `canonical_name` | Có | Tên chuẩn dùng để hiển thị và tìm kiếm |
| `aliases` | Có | Tên khác, nghệ danh, tên viết tắt; danh sách rỗng nếu không có |
| `verification_status` | Có | Đã xác minh, chờ kiểm tra hoặc chưa xác minh |
| `created_at` | Có | Ngày thêm thực thể vào dữ liệu |
| `notes` | Tùy chọn | Ghi chú để phân biệt với đối tượng trùng tên |
| `release_year` | Tùy chọn | Năm phát hành nếu là Song/Album và có nguồn |
| `season_or_year` | Tùy chọn | Mùa/năm nếu là Show/Event |
| `official_url` | Tùy chọn | Trang chính thức xác nhận đối tượng |

Nguồn xác minh được nối qua bảng Bằng chứng hoặc bảng dẫn nguồn riêng nếu cần nhiều nguồn cho một thực thể. Tránh nhét nhiều URL vào một ô.

#### Bảng Quan hệ (`Relation`)

Mỗi dòng đại diện cho một quan hệ duy nhất giữa hai thực thể.

| Trường | Bắt buộc? | Ý nghĩa |
|---|---|---|
| `relation_id` | Có | ID duy nhất, ví dụ `REL_0001` |
| `source_entity_id` | Có | ID thực thể đầu quan hệ |
| `relation_type` | Có | Một loại trong danh sách quan hệ đã thống nhất |
| `target_entity_id` | Có | ID thực thể cuối quan hệ |
| `verification_status` | Có | Đã xác minh, chờ kiểm tra hoặc bị loại |
| `is_derived` | Có | Có/không: quan hệ suy ra từ quan hệ khác hay trích trực tiếp |
| `valid_from` | Tùy chọn | Ngày bắt đầu quan hệ nếu nguồn nói rõ |
| `valid_to` | Tùy chọn | Ngày kết thúc quan hệ nếu nguồn nói rõ |
| `role_detail` | Tùy chọn | Vai trò cụ thể, ví dụ thí sinh, khách mời, huấn luyện viên |
| `notes` | Tùy chọn | Ghi chú làm rõ quan hệ |

Không lưu URL hoặc đoạn trích trực tiếp trong bảng này vì một quan hệ có thể được nhiều tài liệu xác nhận. Bảng Bằng chứng sẽ nối quan hệ với từng nguồn.

#### Bảng Bằng chứng (`Evidence`)

Mỗi dòng đại diện cho một đoạn thông tin trong một tài liệu giúp xác nhận hoặc bác bỏ một quan hệ.

| Trường | Bắt buộc? | Ý nghĩa |
|---|---|---|
| `evidence_id` | Có | ID duy nhất, ví dụ `EVD_0001` |
| `relation_id` | Có | Quan hệ mà bằng chứng này hỗ trợ |
| `document_id` | Có | Tài liệu chứa bằng chứng |
| `quote` | Có | Câu hoặc đoạn trích liên quan |
| `sentence_location` | Có | Số câu, đoạn hoặc vị trí trong tài liệu |
| `extraction_method` | Có | Trích tự động, theo quy tắc hoặc nhập thủ công |
| `review_status` | Có | Đã kiểm tra, chờ kiểm tra hoặc không đủ căn cứ |
| `review_note` | Tùy chọn | Ghi chú về ngữ cảnh hoặc lý do duyệt/loại |
| `confidence_score` | Tùy chọn | Điểm dự đoán của hệ thống nếu có; không thay việc kiểm tra |

#### Quy tắc nhập và chống trùng

- Mỗi dòng có ID riêng; không dùng tên làm ID. ID đã gán phải ổn định qua các lần cập nhật.
- Mỗi `relation_id` đại diện cho một cặp thực thể và một loại quan hệ. Hai nguồn cùng xác nhận thì tạo hai dòng bằng chứng, không tạo hai cạnh.
- Không tạo quan hệ chỉ vì hai người được nhắc trong cùng bài; phải có câu hoặc thông tin đủ xác nhận.
- `published_at` là ngày đăng bài. Chỉ điền `valid_from` khi nguồn nêu rõ thời điểm quan hệ bắt đầu.
- Quan hệ `COLLABORATED_WITH` suy ra từ credit chung cần đặt `is_derived = true` và lưu bằng chứng credit làm căn cứ.
- Trường chưa biết để trống hoặc đánh dấu chưa xác minh; không tự điền theo suy đoán.

**Đầu ra:** Bảng mô tả dữ liệu, quy tắc ID, định nghĩa quan hệ và cách chống trùng.

**Hoàn thành khi:** Lấy một câu mẫu, cả nhóm thống nhất được phải tạo những nút, cạnh và bằng chứng nào; các dòng có thể nối với nhau bằng ID và truy ngược về tài liệu gốc.

## Bước 3. Chọn nguồn và thử khả năng lấy dữ liệu

**Mục đích:** Chọn nguồn có ích và thực sự lấy được thông tin.

**Cách làm:**

1. Lập danh sách nguồn ứng viên: VnExpress, Tuổi Trẻ, Thanh Niên, VTV, VOV, Znews và các báo giải trí; website công ty; kênh chính thức của nghệ sĩ, chương trình và thương hiệu.
2. Ghi URL, chủ sở hữu, loại nguồn, loại quan hệ dự kiến lấy được và cách truy cập.
3. Với mạng xã hội, kiểm tra trạng thái xác minh và đối chiếu chủ sở hữu qua liên kết chính thức; ghi ngày kiểm tra. Không dùng tài khoản giả hoặc fanclub thay nguồn chính thức.
4. Thử lấy vài bài mỗi nguồn, kiểm tra nội dung chính và metadata có đầy đủ không.
5. Ưu tiên RSS, API chính thức hoặc cách truy cập nguồn cho phép. Nếu không lấy được một nền tảng, chuyển sang báo hoặc website chính thức có thông tin tương ứng.

Bắt đầu với 5–10 nguồn; mở rộng đến khoảng 30–50 nguồn nếu cần. Những tên nguồn kể trên là ứng viên, chưa phải kết quả kiểm tra truy cập.

**Đầu ra:** Danh sách nguồn hợp lệ, cách lấy dữ liệu và kết quả thử.

**Hoàn thành khi:** Có nguồn sử dụng được để lấy bộ mẫu, không chỉ có một danh sách URL.

## Bước 4. Thu thập bộ mẫu nhỏ

**Mục đích:** Thử toàn bộ quy trình trước khi lấy hàng nghìn bài.

**Cách làm:**

1. Chọn khoảng 20–30 nghệ sĩ cùng một số công ty/chương trình làm đầu mối.
2. Lấy khoảng 100–200 bài từ nhiều nguồn và có nhiều loại quan hệ. Đây là mức thử đề xuất, không phải yêu cầu cứng.
3. Ưu tiên bài có credit, thông báo phát hành, công ty quản lý hoặc danh sách vai trò trong chương trình.
4. Lưu bản thô cùng URL, tiêu đề, nguồn, ngày đăng và ngày thu thập.
5. Thống kê số bài hữu ích và nguồn thất bại.

**Đầu ra:** Bộ mẫu có thể truy về nguồn gốc.

**Hoàn thành khi:** Có đủ ví dụ để thử nhận diện tên và lấy vài loại quan hệ. Chưa cần chạy thu thập quy mô lớn.

## Bước 5. Làm sạch và loại trùng

**Mục đích:** Giữ đúng phần văn bản cần cho NLP.

**Cách làm theo thứ tự:**

1. Bỏ HTML, menu, quảng cáo và bài viết gợi ý; giữ tiêu đề, nội dung, credit hữu ích.
2. Chuẩn hóa dấu tiếng Việt, khoảng trắng, ký tự lỗi. Không bỏ dấu hoặc viết thường toàn bộ văn bản dùng nhận diện tên.
3. Loại URL trùng và phát hiện bài đăng lại/nội dung gần giống; ghi thông tin nguồn dẫn lại.
4. Lọc tài liệu không thuộc phạm vi hoặc không còn nội dung sử dụng được, lưu lý do loại.
5. Tách đoạn, tách câu, gán ID câu. Giữ ngữ cảnh liền kề khi có “anh”, “cô”, “nam ca sĩ”.
6. Đọc thử 20–30 bài đã làm sạch để kiểm tra có mất tên bài hát, credit hay dấu tiếng Việt không.

**Đầu ra:** Văn bản sạch còn liên kết với bản gốc; thống kê trước/sau lọc và lý do loại.

**Hoàn thành khi:** Từ mỗi câu xử lý được đều tra lại được tài liệu và ngữ cảnh.

## Bước 6. Tạo bộ đáp án mẫu

**Mục đích:** Có căn cứ đo hệ thống đúng hay sai. Bộ này thường gọi là Gold Standard.

**Cách làm:**

1. Chọn tài liệu đại diện cho nguồn và loại quan hệ. Có thể bắt đầu với 50–100 tài liệu rồi bổ sung nhóm còn thiếu.
2. Viết hướng dẫn gán nhãn: thế nào là thực thể, quan hệ hợp lệ, phủ định, tin đồn và dự định tương lai.
3. Đọc và đánh dấu tên thực thể cùng tất cả quan hệ thuộc phạm vi trong tài liệu, kèm chứng cứ. Có cả ví dụ không có quan hệ.
4. Hai người gán nhãn độc lập trên một phần dữ liệu, sau đó đối chiếu và thống nhất bất đồng.
5. Chia phần phát triển và phần kiểm thử giữ riêng, ví dụ 70%/30%. Chia theo tài liệu hoặc nhóm bài trùng, không để câu của cùng một bài nằm ở cả hai phần.
6. Chỉ dùng phần phát triển để chỉnh quy tắc. Nếu huấn luyện mô hình sau này, cần chia thêm phần huấn luyện và kiểm định phù hợp.

Ví dụ giả định: “A phủ nhận gia nhập công ty C” không tạo quan hệ quản lý. “A dự kiến biểu diễn tại Y” chưa xác nhận A đã biểu diễn ở Y.

**Đầu ra:** Hướng dẫn gán nhãn, đáp án mẫu, danh sách chia tập và các bất đồng đã giải quyết.

**Hoàn thành khi:** Có tập kiểm thử chưa được dùng để chỉnh hệ thống.

## Bước 7. Nhận diện và chuẩn hóa tên đối tượng

**Mục đích:** Tìm đúng tên và không tạo nhiều nút cho cùng một đối tượng.

**Phần A — Nhận diện thực thể (NER):**

1. Thử công cụ NLP tiếng Việt có sẵn để tìm tên người và tổ chức.
2. So với đáp án trên tập phát triển để biết công cụ nhận sai/bỏ sót gì.
3. Bổ sung từ điển nghệ danh, nhóm nhạc, bài hát, album và chương trình từ nguồn hợp lệ.
4. Dùng ngữ cảnh như “ca khúc…”, “album…”, “nhạc sĩ…” để hỗ trợ phân loại. Không mặc định mọi tên trong ngoặc kép đều là bài hát.

**Phần B — Chuẩn hóa thực thể (Entity Linking):**

1. Lập bảng tên chuẩn và tên khác đã được xác minh, chẳng hạn tên thật và nghệ danh.
2. Gán một ID ổn định cho mỗi đối tượng; các tên tương đương cùng trỏ về ID đó.
3. Với tên trùng, kiểm tra tác giả, năm, công ty hoặc ngữ cảnh trước khi gộp. Hai bài hát cùng tên chưa chắc là một bài.
4. Đưa trường hợp chưa rõ vào danh sách chờ kiểm tra.

**Đầu ra:** Danh sách tên xuất hiện trong văn bản, bảng thực thể chuẩn hóa và danh sách chưa xác định.

**Hoàn thành khi:** Truy được tên trong câu tới ID và giải thích được lý do gộp/tách đối tượng.

## Bước 8. Trích xuất quan hệ và lưu bằng chứng

**Mục đích:** Biến câu văn thành bộ ba “đối tượng nguồn — quan hệ — đối tượng đích”.

**Cách làm:**

1. Viết ví dụ đúng/sai cho từng loại quan hệ bằng dữ liệu phát triển.
2. Bắt đầu bằng quy tắc ngôn ngữ kết hợp tên đã nhận diện. Ví dụ “X do B sáng tác” gợi ý B — COMPOSED → X.
3. Xác định đúng ai làm gì với đối tượng nào; không nối mọi tên trong câu chỉ vì có từ khóa.
4. Kiểm tra phủ định, tin đồn, thông tin dự kiến và thời gian. Đại từ chưa xác định được thì chuyển chờ duyệt.
5. Mỗi quan hệ lưu câu chứng cứ, tài liệu, phương pháp trích xuất và trạng thái: chấp nhận, cần kiểm tra hoặc loại.
6. Gộp quan hệ trùng, giữ bằng chứng bổ sung.
7. Chỉ suy ra hợp tác từ credit chung sản phẩm/phiên bản đã xác minh. Hai người hát các bản cover khác nhau không tự động là cộng sự.

Chỉ thử mô hình phân loại quan hệ nâng cao khi có đủ dữ liệu gán nhãn và phương pháp ban đầu chưa đáp ứng. Điểm tin cậy do hệ thống gán không thay thế độ chính xác đo thực tế.

**Đầu ra:** Quan hệ ứng viên, bằng chứng và danh sách cần kiểm duyệt.

**Hoàn thành khi:** Một tài liệu đi qua quy trình tạo được các quan hệ có thể kiểm tra lại. Có thể thử nhập một mạng nhỏ vào Neo4j ngay lúc này để phát hiện lỗi thiết kế.

## Bước 9. Đánh giá bản thử trước khi mở rộng

**Mục đích:** Biết phương pháp đủ tốt chưa và lỗi nằm ở đâu.

**Cách làm:**

1. So với đáp án trên tập phát triển; phân loại lỗi: thiếu tên, gộp nhầm, sai quan hệ, đảo chiều, hiểu sai phủ định hoặc thời gian.
2. Sửa lỗi phổ biến và ghi lại thay đổi.
3. Chốt một phiên bản rồi chạy trên tập kiểm thử giữ riêng.
4. Một bộ ba chỉ được tính đúng khi đúng cả hai đối tượng, loại quan hệ và ngữ cảnh thời gian theo hướng dẫn gán nhãn.
5. Báo cáo chỉ số chung và từng loại quan hệ, kèm số mẫu. Nếu đánh giá NER hoặc chuẩn hóa riêng thì trình bày riêng.

| Chỉ số | Ý nghĩa | Cách tính |
|---|---|---|
| Precision | Trong số quan hệ dự đoán, bao nhiêu quan hệ đúng? | Số đúng / số dự đoán |
| Recall | Trong số quan hệ có trong đáp án, tìm được bao nhiêu? | Số đúng / số quan hệ đáp án |
| F1 | Kết hợp precision và recall | 2 × Precision × Recall / (Precision + Recall) |

Ví dụ giả định: đáp án có 100 quan hệ; hệ thống dự đoán 90, trong đó 84 đúng. Precision khoảng 93,3%, recall 84%, F1 khoảng 88,4%. Precision cao vẫn có thể bỏ sót nhiều thông tin.

Nếu dùng lỗi của tập kiểm thử để chỉnh hệ thống, tập đó không còn độc lập cho phiên bản mới; cần tập giữ riêng khác để đánh giá lại. Tách kết quả tự động và kết quả sau sửa thủ công.

**Đầu ra:** Bảng chỉ số thực đo, bảng lỗi và quyết định cần cải thiện hay có thể mở rộng.

**Hoàn thành khi:** Có bằng chứng định lượng về chất lượng. Chỉ công bố trên 90% khi số đo thực tế xác nhận.

## Bước 10. Mở rộng dữ liệu theo phần còn thiếu

**Mục đích:** Đạt số lượng bằng dữ liệu hợp lệ.

**Cách làm:**

1. Đếm nút/cạnh sau chuẩn hóa và loại trùng trên bộ thử.
2. Lập bảng thiếu hụt về số nút, số cạnh và loại quan hệ.
3. Từ nghệ sĩ đã có, tìm thêm tác phẩm, album, cộng sự và công ty; tiếp tục tìm tài liệu cho các đối tượng mới.
4. Thu thập từng đợt rồi làm sạch, chạy NLP, kiểm duyệt và thống kê số nút/cạnh mới.
5. Thiếu quan hệ sáng tác/sản xuất thì tìm credit; thiếu quản lý thì tìm thông báo công ty; thiếu vai trò chương trình thì tìm danh sách theo mùa.
6. Ước lượng lượng bài cần thêm từ hiệu suất thực tế. Ví dụ thiếu 3.000 cạnh và mỗi bài hữu ích tạo trung bình 2 cạnh mới hợp lệ thì dự kiến cần khoảng 1.500 bài hữu ích nữa. Đây là ước lượng, vì các đợt sau có thể trùng nhiều hơn.

Mục tiêu tham khảo: 2.500–4.000 bài báo và 500–1.000 bài đăng chính thức; mạng khoảng 2.500–2.700 nút, 6.500–8.000 cạnh để có dư địa loại lỗi. Số bài không bảo đảm số cạnh; điều chỉnh theo chất lượng và khả năng truy cập.

**Đầu ra:** Dữ liệu mở rộng, bảng tiến độ và nhật ký kiểm duyệt.

**Hoàn thành khi:** Đạt chỉ tiêu đã chốt bằng dữ liệu hợp lệ. Nếu thiếu, mở rộng nguồn có ích; không thêm nút rỗng, cạnh trùng hay quan hệ suy đoán.

## Bước 11. Hoàn thiện Neo4j và kiểm tra graph cuối

**Mục đích:** Có mạng lưới sử dụng và tạo lại được.

**Cách làm:**

1. Tạo loại nút/cạnh và ràng buộc ID theo thiết kế.
2. Nhập nút trước, cạnh sau; liên kết cạnh với bằng chứng.
3. Kiểm tra trùng ID, cạnh thiếu đầu cuối, sai hướng, sai loại nút và thiếu nguồn.
4. Đếm số nút/cạnh nghiệp vụ; không tính nút tài liệu/bằng chứng hoặc cạnh kỹ thuật để đủ chỉ tiêu.
5. Thử tra cứu một nghệ sĩ với các tác phẩm, công ty, chương trình và nguồn cho từng quan hệ.
6. Lấy khoảng 400–600 cạnh để kiểm tra graph cuối, có đại diện các loại quan hệ và nhóm nguồn. Đây là kiểm tra dữ liệu cuối, khác kiểm thử NLP ở bước 9.
7. Đối chiếu hai đầu, loại quan hệ, chứng cứ và thời gian. Nếu lấy mẫu không tỷ lệ với quy mô từng nhóm, tính precision chung theo trọng số quy mô nhóm; không lấy trung bình đơn giản rồi coi là đại diện toàn mạng.
8. Báo cáo cỡ mẫu, cách chọn mẫu và khoảng tin cậy nếu có; không nói toàn bộ cạnh đã được kiểm tra khi chỉ kiểm tra mẫu.
9. Lưu dữ liệu nhập và hướng dẫn để tạo lại graph.

**Đầu ra:** Neo4j hoàn chỉnh, dữ liệu nhập lại, thống kê cấu trúc và kết quả kiểm tra mẫu.

**Hoàn thành khi:** Truy vấn được, lần từ cạnh về nguồn được, và số liệu báo cáo khớp với phiên bản dữ liệu cuối.

## Bước 12. Phân tích mạng và giải thích kết quả

**Mục đích:** Trả lời câu hỏi nghiên cứu bằng dữ liệu, không chỉ vẽ một mạng nhiều nút.

### 12.1. Thống kê mạng đầy đủ

Đếm nút theo loại, cạnh theo quan hệ, phân bố nguồn và thời gian, nút cô lập và thành phần liên thông. Với mạng có hướng, ghi rõ dùng liên thông yếu hay mạnh.

### 12.2. Tạo mạng hợp tác nghệ sĩ riêng

- Chỉ giữ nút Person và quan hệ hợp tác có căn cứ.
- Mỗi cặp nghệ sĩ có một kết nối vô hướng.
- Trọng số là số sản phẩm chung khác nhau, không phải số bài báo nhắc đến.
- Ghi rõ vai trò nào được tính và cách xử lý sản phẩm có nhiều người tham gia.

Không xếp người, bài hát và công ty chung một bảng rồi diễn giải thành ảnh hưởng của nghệ sĩ.

### 12.3. Chọn phép phân tích theo câu hỏi

| Câu hỏi | Cách phân tích | Ý nghĩa |
|---|---|---|
| Ai có nhiều cộng sự? | Degree Centrality | Số nghệ sĩ khác có kết nối |
| Ai có nhiều lượt hợp tác? | Tổng trọng số cạnh | Số lượt hợp tác theo quy ước đếm đã chọn |
| Ai nổi bật về cấu trúc kết nối? | PageRank | Vị trí trong mạng đang nghiên cứu |
| Có nhóm cộng tác nào? | Louvain | Cộng đồng có nhiều kết nối nội bộ |
| Có những cụm tách biệt nào? | Connected Components | Nhóm không có đường nối với nhau |
| Hai người liên hệ qua ai? | Shortest Path | Chuỗi hợp tác ngắn nhất |
| Ai là cầu nối giữa nhóm? | Betweenness, nếu thực hiện | Mức độ nằm trên đường đi ngắn nhất |

Bổ sung số nút/cạnh, bậc trung bình, phân bố bậc, mật độ và quy mô thành phần lớn nhất cho mạng hợp tác. Với công ty, dùng quan hệ Song → Company để đếm bài hát phát hành khác nhau. Chỉ phân tích thay đổi theo thời gian khi đủ dữ liệu thời điểm đáng tin cậy.

### 12.4. Viết nhận xét

Mỗi bảng/hình cần nêu: quan sát được gì; tác phẩm hoặc kết nối nào giúp giải thích; giới hạn do nguồn và phạm vi dữ liệu là gì. Các chỉ số không trực tiếp chứng minh mức độ nổi tiếng hoặc ảnh hưởng ngoài đời.

**Đầu ra:** Bảng thống kê, kết quả thuật toán, biểu đồ phân bố kết nối, hình cộng đồng và nhận xét.

**Hoàn thành khi:** Trả lời được câu hỏi ở bước 1, nêu rõ dữ liệu và phương pháp đứng sau kết luận.

## Bước 13. Báo cáo, demo và bàn giao

**Mục đích:** Người khác hiểu phương pháp, kiểm tra kết quả và chạy lại được.

**Bố cục báo cáo:**

1. Giới thiệu: bài toán, mục tiêu, phạm vi và yêu cầu.
2. Cơ sở lý thuyết: NLP, nhận diện tên, trích xuất quan hệ, graph và phân tích mạng.
3. Dữ liệu: nguồn, cách lấy, làm sạch, gán nhãn và số liệu thực tế.
4. Phương pháp: thiết kế dữ liệu, chuẩn hóa, trích xuất và quản lý bằng chứng.
5. Thực nghiệm: chất lượng NLP, chất lượng graph, quy mô mạng, kết quả phân tích và lỗi.
6. Kết luận: phần đạt/chưa đạt, giới hạn và hướng phát triển.

**Kịch bản demo:** Mở một tài liệu → chỉ tên đối tượng → xem ID chuẩn hóa → xem quan hệ và chứng cứ → tìm trong Neo4j → trình bày một kết quả phân tích. Có thể dùng Neo4j Browser, chưa cần giao diện riêng.

**Danh sách bàn giao:**

- [ ] Phạm vi, thiết kế dữ liệu và danh sách nguồn đã kiểm tra.
- [ ] Metadata tài liệu và dữ liệu được phép chia sẻ.
- [ ] Thực thể, quan hệ và bằng chứng.
- [ ] Bộ đáp án, cách chia tập và kết quả đánh giá.
- [ ] Neo4j và bộ dữ liệu nhập lại.
- [ ] Bảng kết quả, biểu đồ và nhận xét phân tích.
- [ ] Mã nguồn triển khai trên GitHub và hướng dẫn chạy, cấu hình mẫu, mô tả dữ liệu.
- [ ] Báo cáo, slide và kịch bản demo.

**Hoàn thành khi:** Số liệu trong báo cáo, slide và graph thống nhất; người khác có đủ hướng dẫn tái tạo quy trình.

## 3. Lịch đề xuất trong 8 tuần

| Tuần | Công việc | Kết quả cuối tuần |
|---|---|---|
| 1 | Bước 1–3 | Phạm vi, thiết kế dữ liệu, nguồn đã thử |
| 2 | Bước 4–6 | Dữ liệu thử sạch, hướng dẫn gán nhãn, bộ đáp án và tập giữ riêng |
| 3 | Bước 7 | Nhận diện tên và bảng thực thể chuẩn hóa trên mẫu |
| 4 | Bước 8–9 | Quan hệ có chứng cứ, đánh giá bản thử |
| 5 | Bước 10 và thử Neo4j | Mở rộng dữ liệu/loại quan hệ, bảng thiếu hụt, graph thử |
| 6 | Hoàn thiện bước 10–11 | Graph đủ quy mô đã chốt và kiểm tra chất lượng |
| 7 | Bước 12 | Kết quả thuật toán, biểu đồ, nhận xét và giới hạn |
| 8 | Bước 13 | Báo cáo, GitHub, slide và demo |

Viết nhật ký, thống kê và phần báo cáo tương ứng mỗi tuần. Nếu tuần 4 còn sai nhiều, ưu tiên sửa và điều chỉnh tiến độ mở rộng trước khi thêm mô hình nâng cao.

## 4. Phân công công việc

### 4.1. Phân công thu thập nguồn dữ liệu

| Thành viên | Nhóm nguồn phụ trách | Nguồn cụ thể | Công việc |
|---|---|---|---|
| Huy | Mạng xã hội và nền tảng công khai | Meta (Facebook/Instagram), TikTok, YouTube, Spotify và các nền tảng tương tự | Tìm nội dung công khai liên quan đến nghệ sĩ, tác phẩm, chương trình và hợp tác; kiểm tra tài khoản/kênh chính thức; lưu URL, ngày đăng hoặc ngày phát hành, tên tài khoản/kênh và nội dung/bằng chứng cần thiết. Ưu tiên API hoặc cách truy cập được nền tảng cho phép. |
| Đức | Báo chí và website | Báo điện tử, website chính thức của nghệ sĩ, công ty, hãng đĩa, chương trình và đơn vị tổ chức | Tìm bài viết và thông tin chính thức; lưu URL, tên nguồn, tiêu đề, ngày đăng, nội dung liên quan và bằng chứng cho các thực thể/quan hệ. |

Cả hai dùng chung quy tắc chọn nguồn, định dạng lưu và cách đặt ID ở Bước 2. Khi một quan hệ được xác nhận bởi nhiều nguồn, chỉ tạo một quan hệ và bổ sung các bằng chứng tương ứng. Mỗi người kiểm tra mẫu dữ liệu của người còn lại trước khi nhập vào bộ dữ liệu chung.

### 4.2. Các công việc còn lại

| Hạng mục | Phụ trách chính | Phối hợp |
|---|---|---|
| Phạm vi, thiết kế dữ liệu | Huy và Đức | Cùng chốt định nghĩa |
| Bộ đáp án và đánh giá | Phân công theo tiến độ nhóm | Hai người gán nhãn độc lập một phần |
| Nhận diện, chuẩn hóa, trích xuất | Phân công theo tiến độ nhóm | Cùng rà soát lỗi và trường hợp chưa rõ |
| Neo4j và phân tích mạng | Phân công theo tiến độ nhóm | Người còn lại kiểm tra dữ liệu và diễn giải |
| Báo cáo và demo | Huy và Đức | Viết phần phụ trách, đọc chéo |

Nếu nhóm có thêm thành viên, có thể giao riêng NLP, Neo4j/phân tích hoặc đánh giá chất lượng. Mọi thành viên đều tham gia kiểm tra một phần dữ liệu.

## 5. Công cụ dự kiến

Đây là định hướng cho giai đoạn triển khai; chưa cần cài đặt hoặc viết code trong bản kế hoạch này.

| Công việc | Công cụ dự kiến | Vai trò |
|---|---|---|
| Lập nguồn, gán nhãn | Bảng tính | Kiểm tra dữ liệu mẫu |
| Quy trình xử lý | Python | Kết nối các bước |
| Thu thập web | Requests, BeautifulSoup, công cụ RSS | Lấy nội dung từ nguồn cho phép |
| Xử lý bảng | Pandas | Làm sạch và thống kê |
| NLP ban đầu | Công cụ tiếng Việt như Underthesea, từ điển, quy tắc | Thử nhận tên và quan hệ |
| NLP nâng cao | Mô hình phù hợp như PhoBERT | Thử phân loại khi đủ dữ liệu gán nhãn |
| Lưu graph | Neo4j | Lưu và truy vấn |
| Thuật toán mạng | Neo4j GDS hoặc thư viện graph phù hợp | Tính chỉ số và cộng đồng |
| Trực quan hóa | Neo4j Browser, Gephi | Minh họa mạng và kết quả |
| Quản lý phiên bản | GitHub | Lưu mã nguồn và hướng dẫn |

Khi triển khai mới kiểm tra phiên bản, khả năng hỗ trợ và môi trường cài đặt. Không mặc định NER có sẵn sẽ nhận đúng mọi bài hát, album và chương trình.

## 6. Gặp vấn đề thì xử lý thế nào?

| Vấn đề | Việc cần làm |
|---|---|
| Không lấy được mạng xã hội | Tìm báo/website chính thức có thông tin tương ứng |
| Nhiều bài nhưng ít quan hệ | Ưu tiên credit, danh sách tác phẩm và thông báo vai trò |
| Thiếu nút/cạnh | Đo thiếu hụt, mở rộng theo thực thể và loại quan hệ |
| Gộp nhầm người/bài hát | Sửa bảng ID và xử lý lại quan hệ bị ảnh hưởng |
| Nguồn mâu thuẫn | Giữ bằng chứng, xét thời gian, chờ duyệt nếu chưa rõ |
| Precision thấp | Phân tích lỗi, sửa trên tập phát triển, đánh giá độc lập lại và báo cáo recall |
| Ít mẫu ở một loại quan hệ | Bổ sung gán nhãn, công bố cỡ mẫu, chưa kết luận từ vài ví dụ |
| Gần hết thời gian | Ưu tiên dữ liệu, bằng chứng, đánh giá và graph; bỏ phần nâng cao |

**Việc bắt đầu ngay:** Chốt yêu cầu → thống nhất nút/cạnh → thử nguồn → lấy bộ mẫu nhỏ. Chạy được toàn bộ luồng trên mẫu rồi mới mở rộng quy mô.
