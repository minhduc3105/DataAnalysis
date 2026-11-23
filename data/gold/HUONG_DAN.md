# Hướng dẫn gán nhãn bộ gold

Mỗi người chỉ gán các dòng có `annotator` là tên mình hoặc `Cả hai`. Dòng `Cả hai` phải gán **độc lập, không xem nhãn của người kia**, vì chúng dùng để tính Cohen's kappa. Hạn: tối 25/11.

## 1. `gold_relations.csv` — chấm cạnh trong đồ thị (200 dòng)

Đọc `source_name` –`relation_type`→ `target_name`, câu `quote` và mở `url` nếu câu chưa đủ.

| Cột | Điền |
|---|---|
| `label_huy` / `label_duc` | `đúng`, `sai` hoặc `không rõ` |
| `correct_relation_type` | Chỉ khi `sai`: loại đúng (bảng dưới) hoặc `NONE` nếu hai bên không có quan hệ |
| `note` | Lý do ngắn khi `sai` / `không rõ` (sai người, sai bài, sai hướng, tên rác…) |

`đúng` khi đủ cả ba: đúng hai thực thể (không phải tên rác hay người trùng tên), đúng loại quan hệ, đúng hướng. `COLLABORATED_WITH` là đúng khi hai người cùng trình bày hoặc cùng làm một bài.

## 2. `gold_sentences.csv` — đáp án cho NER và quan hệ (100 câu)

`suggested_entities` là gợi ý tự động từ từ điển, **có cả gợi ý sai**: xóa cái sai, thêm cái thiếu. Điền vào cột của mình (`entities_huy`/`relations_huy` hoặc `entities_duc`/`relations_duc`).

- Thực thể: `Tên như trong câu|Loại; Tên|Loại`. Loại: `Person`, `Group`, `Song`, `Album`, `Company`, `Show`, `Event`, `Brand`. Chỉ ghi thực thể thuộc ngành âm nhạc/giải trí; người ngoài ngành (quan chức, địa danh) không ghi. Không có thực thể nào thì ghi `NONE`.
- Quan hệ: `A|LOẠI|B; …`, chỉ khi **chính câu đó** nói ra quan hệ. Cùng xuất hiện trong câu không đủ. Không có quan hệ thì ghi `NONE`.

## Loại quan hệ

| Loại | Hướng | Nghĩa |
|---|---|---|
| PERFORMED | Person/Group → Song | Trình bày bài hát |
| FEATURED_ON | Person/Group → Song | Khách mời (feat.) |
| COMPOSED | Person → Song | Sáng tác, viết lời |
| PRODUCED | Person → Song | Sản xuất, hòa âm phối khí |
| RELEASED_BY | Song → Company | Công ty/label phát hành |
| TRACK_OF | Song → Album | Bài thuộc album/EP |
| MEMBER_OF | Person → Group | Thành viên nhóm |
| CONTESTANT_ON | Person → Show | Thí sinh |
| JUDGE_ON | Person → Show | Giám khảo, huấn luyện viên |
| PERFORMED_AT | Person/Group → Show/Event | Biểu diễn, khách mời tại chương trình/sự kiện |
| ORGANIZED_BY | Show/Event → Company | Đơn vị tổ chức, sản xuất |
| AMBASSADOR_OF | Person/Group → Brand | Đại sứ, hợp tác quảng cáo |
| COLLABORATED_WITH | Person ↔ Person | Cùng làm một sản phẩm cụ thể |
| DISPUTED_WITH | Person/Company ↔ Person/Company | Tranh chấp, kiện tụng, cáo buộc công khai (tin đồn không tính) |

Ví dụ: “Được biết, ca khúc thuộc album đầu tay Colours … Hứa Kim Tuyền dành tặng AMEE” → thực thể `Colours|Album; Hứa Kim Tuyền|Person; AMEE|Person`, quan hệ `NONE` (câu không nói rõ ai sáng tác hay trình bày bài nào).
