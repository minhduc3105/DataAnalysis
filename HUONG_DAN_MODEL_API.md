# API mô hình (Huy) — khởi động và dùng

API chạy ở `http://127.0.0.1:8001` (giá trị mặc định của `MODEL_API_BASE_URL`), theo hợp đồng `schemas/model_contract_v1.json`. Quy ước đầu ra trích xuất ở `schemas/extraction_output_v1.md`.

## Cần có

1. Ollama đang chạy (`ollama serve`, hoặc mở ứng dụng Ollama).
2. Hai mô hình:
   ```bash
   ollama pull qwen3:8b
   ollama pull bge-m3
   ```
3. `data/processed/web/articles_ready.csv` và `data/interim/graph/entities.csv`: `/extract` dùng hai file này làm từ điển để chọn câu ứng viên.

## Khởi động

```bash
uv run python main.py model-api            # --port 8001 --host 127.0.0.1 là mặc định
```

Kiểm tra:

```bash
curl http://127.0.0.1:8001/health
uv run python main.py doctor --model        # bộ kiểm /embed có sẵn của Đức
```

`/health` trả `status: ok` khi Ollama chạy và có đủ hai mô hình. Thiếu mô hình thì trả `missing_model` và `models_ready` cho biết mô hình nào còn thiếu.

## Endpoint

| Endpoint | Đầu vào | Đầu ra | Thời gian |
|---|---|---|---|
| `POST /embed` | `{"schema_version": "vn-music-radar.v1", "texts": [...]}`, 1–256 chuỗi, không chuỗi rỗng | `{"model_version": "bge-m3", "dimensions": 1024, "vectors": [...]}`, vector đã chuẩn hóa L2 nên dùng cosine | khoảng 0,1–1 s cho mỗi lô 64 chuỗi |
| `POST /extract` | `{"document_id", "schema_version", "text"}` | kết quả trích xuất đúng `extractResponse` | khoảng 7 s cho mỗi câu ứng viên; trung bình 4–5 câu/bài, bài dài có thể quá 2 phút |
| `GET /health` | | trạng thái Ollama và mô hình | |

Lỗi:

- `422`: request sai hợp đồng (thiếu trường, thừa trường, `schema_version` sai, có chuỗi rỗng trong `texts`).
- `503`: Ollama chưa chạy, thiếu mô hình, hoặc Ollama lỗi giữa chừng. Thông báo ghi cách xử lý. `ModelClient` tự gọi lại 2 lần.

## Lưu ý

- `/extract` lần đầu mất thêm 10–20 s để nạp từ điển. Câu đã trích được lưu cache (`data/interim/model_handoff/slm_cache_qwen3_8b_v2.jsonl`), nên gọi lại cùng bài sẽ trả ngay.
- Với bài dài, `ModelClient` timeout 120 s có thể không đủ. Đặt `MODEL_API_TIMEOUT=600` nếu gọi `/extract` từng bài. Nhập số lượng lớn thì dùng file JSONL bàn giao (`extractions.jsonl`), không gọi `/extract` hàng loạt.
- GPU chỉ chạy một yêu cầu SLM một lúc, nên các request `/extract` đồng thời sẽ xếp hàng. `/embed` không phải chờ `/extract`.
- `/answer` và `/summarize` chưa có; sẽ bổ sung ở bước tiếp theo trên cùng cổng 8001.
