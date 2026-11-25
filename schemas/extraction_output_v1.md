# Đầu ra trích xuất SLM — đặc tả v1

Hợp đồng gốc là `schemas/model_contract_v1.json` (`extractResponse`). File này ghi những quy ước bên mô hình mà JSON Schema không diễn tả được.

## File

- `data/interim/model_handoff/extractions.jsonl`: mỗi dòng là một JSON object, tức một kết quả `/extract` cho một bài. Mẫu 20 bài: `extractions_sample20.jsonl`.
- Mỗi bài đầu vào có **đúng một dòng**, kể cả bài không trích được gì (khi đó `entities` và `relations` rỗng).
- `extraction_log_*.csv`: những mention/quan hệ bị bỏ và lý do. Chỉ để tra cứu, không nhập.

## Trường

| Trường | Kiểu | Quy ước |
|---|---|---|
| `document_id` | string | `document_id` trong `articles_ready.csv` hoặc trong luồng tin mới |
| `schema_version` | string | luôn là `vn-music-radar.v1` |
| `model_version` | string | `<mô hình>+prompt-<phiên bản>`, hiện là `qwen3:8b+prompt-v2`. Đổi mô hình hoặc prompt thì chuỗi này đổi |
| `entities[].mention_id` | string | `m0001`, `m0002`… đánh số theo thứ tự xuất hiện, **chỉ duy nhất trong một bài**. Khóa toàn cục là (`document_id`, `mention_id`, `model_version`) |
| `entities[].text` | string | chuỗi con nguyên văn: `text == văn_bản[start:end]` |
| `entities[].type` | string | một trong 8 loại của hợp đồng |
| `entities[].start`, `end` | int | vị trí ký tự (Python, code point, nửa mở `[start, end)`) trong `body_text`; bài không có `body_text` thì tính trong `content`. Văn bản đều ở chuẩn NFC. JavaScript đếm theo UTF-16, nên phải đổi lại nếu cần highlight ký tự ngoài BMP |
| `relations[].head_mention_id`, `tail_mention_id` | string | trỏ tới mention **trong cùng câu**; hướng theo `relation_signatures`. `COLLABORATED_WITH`, `DISPUTED_WITH` đối xứng, thứ tự head/tail không mang nghĩa |
| `relations[].evidence` | string | chuỗi con nguyên văn của bài: đoạn trích do SLM chọn; nếu đoạn đó không khớp nguyên văn thì là cả câu |
| `relations[].confidence` | number | **quy ước, không phải xác suất**: 0.9 khi bằng chứng là đoạn trích nguyên văn, 0.6 khi phải lùi về cả câu. Không dùng làm ngưỡng tự nhận cạnh |

## Phạm vi trích xuất

- Chỉ những câu dài 40–400 ký tự, có ≥ 2 thực thể khớp từ điển đồ thị, trong đó có ít nhất một nghệ sĩ, mới được gửi vào SLM. Đây cũng là tiêu chí lấy mẫu gold, nên số đo bên dưới đại diện cho đúng tập câu này. Khoảng 13,5% số câu là ứng viên.
- `entities` **không liệt kê đầy đủ** thực thể trong bài: chỉ có những thực thể SLM tìm thấy trong câu ứng viên. Cùng một tên xuất hiện ở hai câu sẽ có hai `mention_id`.
- Quan hệ chỉ được trích trong phạm vi một câu, không ghép hai câu kề nhau.
- Mention mà SLM trả về nhưng không tìm lại được trong câu thì bị bỏ. Quan hệ sai kiểu nút, có head hoặc tail không nằm trong câu, hoặc có head = tail cũng bị bỏ (hậu kiểm).

## Chất lượng (để người duyệt biết nên nghi ngờ gì)

| Đo | Kết quả |
|---|---|
| Gold test (70 câu, 45 quan hệ) | F1 thực thể 0,82; quan hệ P 0,45 / R 0,64 / F1 0,53 |
| Đọc tay 20 bài | thực thể 160/190 đúng (84%); quan hệ 25/49 đúng (51%) |

Lỗi hay gặp, người duyệt nên `rejected`:

- Nhóm lập tạm trong show ("Nhà Hoa Lửa", "team Nắng", "đội …") bị gán `Group` kèm `MEMBER_OF`/`PERFORMED`.
- Khách dự tiệc cưới/sự kiện riêng bị gán `PERFORMED_AT` (tail là "lễ cưới", địa danh) hoặc các cặp đôi bị gán `COLLABORATED_WITH`.
- Thí sinh show giấu mặt bị gán `PERFORMED_AT` thay vì `CONTESTANT_ON`.
- Tên kèm chú thích: "Thỏ (Da LAB)", "NS Đức Trí".
- Khoảng 2% bài có đuôi "Tin liên quan / Xem thêm" của bài khác, nên thực thể trong phần đuôi đó không thuộc bài.
