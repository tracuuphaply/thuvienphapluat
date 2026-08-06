# Vận hành hệ thống

Tài liệu này mô tả các script bảo trì và cách chạy chúng. Phần kiến trúc tổng
thể xem `HUONG_DAN_CHUYEN_GIAO.md`.

## Lịch chạy hằng ngày

Dùng **launchd**, không dùng cron: cron không chạy bù. Máy ngủ hoặc tắt vào đúng
giờ hẹn là mất hẳn ngày đó và không có dấu vết nào.

```bash
./scripts/install_scheduler.sh          # cài, chạy 6h sáng
./scripts/install_scheduler.sh 7 30     # chạy 7h30
./scripts/install_scheduler.sh --uninstall

launchctl kickstart -k gui/$(id -u)/vn.legalvault.daily   # chạy thử ngay
```

`scripts/run_daily.sh` làm ba việc theo thứ tự: cào văn bản mới → đồng bộ vault
và RAG index → sao lưu. Bước sao lưu chạy **kể cả khi pipeline lỗi**.

Chỉ một lần chạy được phép tại một thời điểm — `pipeline_lock()` giữ
`data/pipeline.lock`. Lần chạy thứ hai thoát yên lặng thay vì đua ghi dữ liệu.

## Log

`data/logs/pipeline.log`, xoay vòng theo ngày, giữ 30 ngày. launchd ghi thêm
`launchd.out.log` và `launchd.err.log`.

## Sao lưu

`python -m src.utils.backup` — giữ 30 ngày trong `data/backups/`:

| File | Nội dung |
|---|---|
| `db_<ngày>.sqlite.gz` | legal_docs.db |
| `rag_<ngày>.sqlite.gz` | rag.db (chunk + vector + đồ thị) |
| `files_<ngày>.tar.gz` | moj, metadata, clean_text, chunks, Legal-Vault |

Sao lưu SQLite dùng `VACUUM INTO`, không copy byte thô: copy file đang mở có thể
tạo bản sao rách, và bỏ quên file `-wal` là mất giao dịch đã commit.

**Chưa có quy trình kiểm chứng phục hồi.** Nên thử khôi phục một bản vào thư mục
tạm định kỳ.

## Bảo trì dữ liệu

### Dò lại mã quan hệ của API Bộ Tư pháp

```bash
python -m scripts.probe_reference_types 200
```

Gateway trả quan hệ dưới dạng số nguyên `referenceType` và **không có tài liệu
công khai**. Script suy ra nghĩa từ hai tín hiệu độc lập: động từ đứng trước số
hiệu đích trong toàn văn, và tỷ lệ văn bản đích đã có `effTo`.

Đã chốt: `1=Bãi bỏ, 3=Căn cứ, 9=Căn cứ, 10=Sửa đổi bổ sung, 12=Thay thế`.
Mã `4, 5, 7, 8, 11` chưa đủ mẫu nên mang nhãn `"Chưa xác định (mã N)"` — chạy
lại script khi kho lớn hơn để chốt nốt. **Đừng đoán**: đoán bừa chính là nguyên
nhân khiến 82% đồ thị từng bị gán sai.

### Dựng lại đồ thị quan hệ

```bash
python -m scripts.rebuild_reference_graph [--dry-run]
```

Chạy sau khi sửa `REFERENCE_TYPE_LABELS`. Lấy lại quan hệ từ nguồn thay vì đổi
tên nhãn — nhãn cũ đã trộn lẫn nhiều mã nên không tách ngược ra được.

### Bổ sung văn bản còn thiếu

```bash
python -m scripts.backfill_cited_documents --dry-run
python -m scripts.backfill_cited_documents --limit 701
```

Tải các văn bản đã được kho dẫn chiếu nhưng chưa có — đây chính là các luật nền
tảng. Lấy `targetDocument.id` từ payload quan hệ rồi fetch theo id.

> **Không dùng `search_by_doc_num`**: endpoint `/doc/all` bỏ qua mọi tham số lọc
> (đã thử `keyword`, `docNum`, `searchText`, `q`, `filter`, `text`, `soHieu`),
> nên tra theo số hiệu luôn thất bại.

### Bổ sung văn bản lịch sử

```bash
python -m scripts.backfill_historical --dry-run --until 2024-08-01
python -m scripts.backfill_historical --until 2024-08-01
```

Lật trang lùi theo `issueDate` cho tới mốc chỉ định. Mặc định 24 tháng, khớp yêu
cầu "văn bản ban hành trong 24 tháng gần nhất" ở Bước 1 của prompt báo cáo.
Càng lùi sâu càng lâu: khoảng 240 trang cho mỗi năm.

Sau khi bổ sung, chạy lại index để nhúng các đoạn mới:

```bash
python -m src.main --sync-vault-only
python -m src.main --sync-rag-only
```

### Migration schema

```bash
python -m scripts.migrate_doc_key [--dry-run]
```

Bỏ `UNIQUE(doc_num)`, thay bằng `doc_key = số hiệu + cơ quan`. Số hiệu chỉ duy
nhất trong phạm vi cơ quan ban hành: `67/2026/QĐ-UBND` tồn tại ở 18 tỉnh, ràng
buộc cũ khiến bản thứ hai trở đi bị nuốt im lặng.

Script tự sao lưu trước khi đổi và dừng lại nếu phát hiện khoá trùng.

> `doc_key` phải được tính bằng `make_doc_key()` của Python, **không** bằng SQL:
> `lower()` của SQLite chỉ xử lý ASCII nên `lower('QĐ')` ra `'qĐ'`, tạo khoá mà
> runtime không khớp lại được.

## Vector search

Cần `sqlite-vec` (`pip install sqlite-vec`). Số chiều lấy từ model đang dùng qua
`embedding_dimension()`, không hardcode — bảng `legal_chunks_vec` tự dựng lại
nếu số chiều đổi, và mọi vector lệch chiều bị từ chối ngay khi ghi.

| Biến môi trường | Ý nghĩa |
|---|---|
| `EMBEDDING_MODEL` | ép model nhúng |
| `EMBEDDING_DIM` | ép số chiều |
| `REPORT_MODEL` | model sinh báo cáo |
| `REPORT_MAX_TOKENS` | giới hạn độ dài báo cáo (mặc định 16000) |
| `REPORT_PROMPT_PATH` | mẫu prompt ngoài repo |

## Test

```bash
pytest                    # tất cả
pytest -m "not data"      # chỉ test đơn vị, không cần dữ liệu thật
pytest -m data            # kiểm tra sức khoẻ kho dữ liệu thật
```

Nhóm `data` chạy trên `data/` và `Legal-Vault/` để bắt hồi quy sau mỗi lần cào:
không văn bản cấp tỉnh nào được "bãi bỏ" luật Quốc hội, mọi ngành đều truy xuất
được, chunk không mất metadata, file vault có nội dung.
