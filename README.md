# Hệ thống theo dõi văn bản pháp luật cho doanh nghiệp

> "Não Pháp luật" Gatlas — cào văn bản quy phạm pháp luật, lưu trữ, chấm điểm tác động
> theo ngành, và sinh báo cáo pháp lý mà mọi số hiệu trích dẫn đều truy ngược được.

**Repo này PRIVATE và phải giữ nguyên như vậy.** Nó chứa `.env` với khoá API thật,
`credentials/` với token Google, và `data/chrome_profile/` với cookie đăng nhập TVPL.
Trang tra cứu công khai nằm ở một repo **riêng** (`legal-vault-public`) chỉ chứa nội
dung đã sinh — xem [§ Trang công khai](#6-trang-công-khai).

## Dây chuyền

```
cào → Google Drive → vault Markdown → RAG (FTS5 + vector) → 3 loại báo cáo PDF
                                   ↘ trang tra cứu công khai (GitHub Pages)
```

## Quy mô hiện tại

| | |
|---|---:|
| Văn bản trong kho | 4.467 |
| Quan hệ dẫn chiếu | 27.142 |
| Đoạn đã nhúng vector | 144.568 |
| Điểm tác động ngành | 77.847 |
| Trang đã đăng công khai | 4.200 |

## Cài đặt

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium          # cho phần tải .docx từ TVPL
cp .env.example .env                 # rồi điền giá trị thật
python -m scripts.setup_db
```

## Chạy

```bash
python -m src.main                       # pipeline cào đầy đủ
python -m src.main --dry-run             # xem trước, không gửi Telegram
python -m src.main --moj-only            # bỏ TVPL, không cần đăng nhập
python -m src.main --upload-only         # chỉ đẩy phần còn nợ lên mây
python -m src.main --limit 5             # chạy thử trên 5 văn bản

python -m scripts.run_closure            # truy vết bao đóng dẫn chiếu
python -m scripts.compute_impact         # chấm điểm tác động 21 ngành
python -m scripts.run_report_worker      # rút hàng đợi báo cáo
python -m scripts.publish_site           # sinh nội dung trang công khai
python -m scripts.gdrive_check           # kiểm kết nối Drive
```

Chạy tự động: `scripts/install_scheduler.sh` cài hai launchd agent — `run_daily.sh`
(cào + báo cáo, hằng ngày) và `run_quarterly.sh` (báo cáo tổng hợp ngành, 1/1 · 1/4 ·
1/7 · 1/10).

## Cấu trúc

| Gói | Việc |
|---|---|
| `src/sources/` | Cào: RSS TVPL, API Bộ Tư pháp, tải `.docx` bằng Playwright |
| `src/pipeline/` | Gộp trùng, truy vết bao đóng dẫn chiếu |
| `src/legal/` | Dữ kiện pháp lý: thứ bậc văn bản, tỉnh thành (có sáp nhập 2025), cờ hiệu lực, 27 lĩnh vực TVPL |
| `src/analysis/` | Chấm điểm tác động 21 ngành VSIC — đếm từ ràng buộc × liên quan ngành, phỏng theo RegData |
| `src/storage/` | ORM, migration, Google Drive, hàng đợi upload |
| `src/rag/` | Truy xuất lai (FTS5 + sqlite-vec + RRF), prompt, bộ sinh 3 loại báo cáo, kiểm trích dẫn |
| `src/obsidian/` | Vault Markdown cho Obsidian cục bộ |
| `src/publish/` | Sinh trang tra cứu công khai và link từ PDF về trang đó |
| `src/notification/` | Digest Telegram |

## Điều khiển qua Telegram

Cào dữ liệu chạy ngầm, **không nhắn tin** — kết quả xem trực tiếp trên Google
Drive. Telegram chỉ dùng để điều khiển báo cáo và nhận file.

| Lệnh | Việc |
|---|---|
| `/baocao` | Hướng dẫn + số báo cáo đang chờ |
| `/baocao a <mã ngành>` | Đặt báo cáo tổng hợp ngành |
| `/baocao b` | Đặt báo cáo cập nhật văn bản mới |
| `/nganh` | 21 mã ngành VSIC |
| `/hangdoi` | Báo cáo đang chờ / đang chạy / vừa xong |
| `/xem <id>` | Chi tiết một báo cáo, kèm file PDF |
| `/huy <id>` | Huỷ báo cáo còn đang chờ |
| `/chay` | Chạy hàng đợi ngay, không đợi lịch |

Mọi lệnh đều **xếp hàng chứ không sinh báo cáo tại chỗ**, để cổng kiểm trích dẫn
ở tầng worker không thể đi vòng. Báo cáo loại (c) không đặt tay được — hệ thống
tự tạo sau khi (b) chạy xong.

Chạy bot: `python -m src.notification.telegram_bot_server`

## Ba loại báo cáo

| Loại | Kích hoạt | Nội dung |
|---|---|---|
| **(a)** Tổng hợp ngành | Hết quý | Toàn cảnh khung pháp lý một ngành VSIC |
| **(b)** Cập nhật văn bản mới | Có văn bản mới / đổi hiệu lực | Cái gì đổi, ai phải làm gì, từ ngày nào |
| **(c)** Chuyên sâu doanh nghiệp | Sau khi (b) xong | Văn bản mới chạm vào đâu trong hoạt động hằng ngày |

Báo cáo viết cho **chủ doanh nghiệp, không phải luật sư** — quy tắc giọng văn dùng
chung ở `src/rag/prompts/_chung/giong_van_doanh_nghiep.md`.

Hai chốt chặn không được gỡ:

- **Kiểm trích dẫn là cổng cứng.** Số hiệu không có trong kho thì báo cáo bị chặn
  xuất bản (`BLOCKED_CITATION`), không phải cảnh báo.
- **Link và biểu đồ do code chèn, không để mô hình sinh.** URL do mô hình viết là URL
  bịa; biểu đồ do mô hình vẽ còn nguy hiểm hơn vì người đọc tin vào hình hơn chữ.

## 6. Trang công khai

Repo riêng: **[minhle2412/legal-vault-public](https://github.com/minhle2412/legal-vault-public)**
→ https://minhle2412.github.io/legal-vault-public

Chỉ đăng **dữ kiện + đồ thị dẫn chiếu, không đăng toàn văn**. Căn cứ: Điều 15 Luật Sở
hữu trí tuệ (VBQPPL không thuộc đối tượng bảo hộ quyền tác giả). Phần giá trị gia tăng
của cơ sở dữ liệu thương mại thì không tự do, nên không dùng.

Cập nhật: `python -m scripts.publish_site` rồi chép `build/public-vault/content` sang
repo kia và push.

## Khoá cần có

| Khoá | Dùng cho | Lấy ở đâu |
|---|---|---|
| Tài khoản TVPL | Tải bản `.docx` biên tập | Tài khoản công ty |
| Telegram Bot Token | Digest hằng ngày | @BotFather |
| Google Drive **OAuth** | Lưu trữ đám mây | Xem cảnh báo bên dưới |
| Khoá LLM | Sinh báo cáo + nhúng vector | Xem cảnh báo bên dưới |

> **Google Drive phải dùng OAuth ứng dụng cài đặt, KHÔNG dùng service account.**
> Google cấp cho service account hạn mức lưu trữ 0 GB nên mọi lần upload trả
> `403 storageQuotaExceeded`, và không xin thêm quota được. Dùng scope duy nhất
> `drive.file` (không nhạy cảm, không cần Google thẩm định) và **phải bấm PUBLISH APP**
> — để consent screen ở trạng thái Testing thì refresh token hết hạn sau đúng 7 ngày và
> pipeline chết câm. Quy trình đầy đủ ở `HUONG_DAN_CHUYEN_GIAO.md`.

> **Nhà cung cấp LLM cũ đã đóng cửa.** v98store trả `service_migrated` và yêu cầu tạo
> tài khoản mới ở nơi khác. Chừng nào chưa thay `OPENAI_API_BASE` + `V98_API_KEY` trong
> `.env` thì **không sinh được báo cáo mới**; phần cào, chấm điểm và trang công khai vẫn
> chạy bình thường. `llm_api_key()` ưu tiên v98 → OpenAI → Gemini nên đổi nhà cung cấp
> chỉ là điền khoá tương ứng.

## Tài liệu

| File | Nội dung |
|---|---|
| `HUONG_DAN_CHUYEN_GIAO.md` | Bàn giao đầy đủ: kiến trúc, quy trình, cấu hình |
| `docs/VAN_HANH.md` | Vận hành hằng ngày, sao lưu, xử lý sự cố |
| `docs/VIEC_CAN_BAN_LAM.md` | Việc cần người vận hành tự làm |

## Kiểm thử

```bash
python -m pytest -q
```

596 test, 1 bỏ qua. Nhiều test ghi lại **lỗi đã xảy ra thật** kèm số đo — đọc docstring
của chúng trước khi sửa phần liên quan.
