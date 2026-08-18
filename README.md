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

cào biểu mẫu → phễu 3 tầng (lĩnh vực → quy tắc → LLM) → DOCX/PDF dựng lại
                                   ↘ lệnh Telegram /bieumau
                                   ↘ trang tra cứu công khai
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
python -m src.main --dry-run             # xem trước, không ghi gì
python -m src.main --moj-only            # bỏ TVPL, không cần đăng nhập
python -m src.main --upload-only         # chỉ đẩy phần còn nợ lên mây
python -m src.main --limit 5             # chạy thử trên 5 văn bản

python -m scripts.run_closure            # truy vết bao đóng dẫn chiếu
python -m scripts.compute_impact         # chấm điểm tác động 21 ngành
python -m scripts.run_report_worker      # rút hàng đợi báo cáo
python -m scripts.publish_site           # sinh nội dung trang công khai
python -m scripts.gdrive_check           # kiểm kết nối Drive

python -m scripts.crawl_forms --source hopdong   # cào 662 mẫu hợp đồng
python -m scripts.crawl_forms --source bieumau   # cào biểu mẫu theo lĩnh vực
python -m scripts.classify_forms                 # phễu lọc mẫu doanh nghiệp
python -m scripts.build_forms                    # dựng DOCX + PDF
```

Chạy tự động: `scripts/install_scheduler.sh` cài ba launchd agent — `run_daily.sh`
(cào + báo cáo, hằng ngày), `run_weekly_forms.sh` (làm mới kho biểu mẫu, Chủ nhật) và
`run_quarterly.sh` (báo cáo tổng hợp ngành, 1/1 · 1/4 · 1/7 · 1/10).

## Cấu trúc

| Gói | Việc |
|---|---|
| `src/sources/` | Cào: RSS TVPL, API Bộ Tư pháp, tải `.docx` bằng Playwright, hai kho biểu mẫu |
| `src/forms/` | Phễu lọc biểu mẫu doanh nghiệp, dựng lại DOCX/PDF, tìm kiếm |
| `src/pipeline/` | Gộp trùng, truy vết bao đóng dẫn chiếu |
| `src/legal/` | Dữ kiện pháp lý: thứ bậc văn bản, tỉnh thành (có sáp nhập 2025), cờ hiệu lực, 27 lĩnh vực TVPL |
| `src/analysis/` | Chấm điểm tác động 21 ngành VSIC — đếm từ ràng buộc × liên quan ngành, phỏng theo RegData |
| `src/storage/` | ORM, migration, Google Drive, hàng đợi upload |
| `src/rag/` | Truy xuất lai (FTS5 + sqlite-vec + RRF), prompt, bộ sinh 3 loại báo cáo, kiểm trích dẫn |
| `src/obsidian/` | Vault Markdown cho Obsidian cục bộ |
| `src/publish/` | Sinh trang tra cứu công khai và link từ PDF về trang đó |
| `src/notification/` | Bot Telegram điều khiển báo cáo, cảnh báo lỗi |

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
| `/bieumau` | Danh sách 12 nhóm nghiệp vụ kèm số lượng |
| `/bieumau <từ khoá>` | Tìm biểu mẫu |
| `/bieumau nhom <mã>` | Liệt kê cả nhóm nghiệp vụ |
| `/bieumau <mã mẫu>` | Gửi file DOCX + PDF |

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

**Đọc trước, tổng hợp sau.** Cả ba loại đều chạy qua hai bước. Bước ĐỌC
(`src/rag/reports/summarizer.py`) đọc HẾT toàn văn từng văn bản trong báo cáo rồi
chắt thành insight neo vào Điều/Khoản (nghĩa vụ, ngưỡng, mốc, chế tài); bước TỔNG
HỢP dựng báo cáo từ các insight đó thay vì chỉ liệt kê metadata. Bản tóm tắt được
cache theo `doc_key` trong `rag.db` (chỉ dựng lại khi nội dung đổi), nên cùng một
đạo luật không bị tóm tắt lại ở mỗi báo cáo ngành. Làm ấm cache trước khi sinh
báo cáo hàng loạt:

```bash
python -m scripts.backfill_document_insights
```

Hai chốt chặn không được gỡ:

- **Kiểm trích dẫn là cổng cứng.** Số hiệu không có trong kho thì báo cáo bị chặn
  xuất bản (`BLOCKED_CITATION`), không phải cảnh báo.
- **Link và biểu đồ do code chèn, không để mô hình sinh.** URL do mô hình viết là URL
  bịa; biểu đồ do mô hình vẽ còn nguy hiểm hơn vì người đọc tin vào hình hơn chữ.

## Kho biểu mẫu cho doanh nghiệp

Nguồn: hai kho tách biệt của Thư viện Pháp luật — `/hopdong` (662 mẫu hợp đồng) và
`/bieumau` (33.820 biểu mẫu). Không cần tài khoản TVPL: ruột biểu mẫu hiện với khách
vãng lai. Vẫn cần Chrome thật vì Cloudflare chặn mọi thứ không phải điều hướng trình
duyệt.

**Chỉ giữ mẫu doanh nghiệp thật sự phải điền.** Lọc theo lĩnh vực là không đủ: 21 lĩnh
vực nghi liên quan doanh nghiệp cộng lại đã 17.385 mẫu, mà riêng nhóm "Kế toán – Kiểm
toán" chứa cả biểu quyết toán ngân sách của Kho bạc Nhà nước. Thứ phân biệt là **ai
cầm bút điền**, nên phễu chạy ba tầng, mỗi tầng đắt hơn tầng trước:

| Tầng | Cách làm | Chi phí |
|---|---|---|
| 1 | Whitelist 21 lĩnh vực | miễn phí |
| 2 | Quy tắc từ khoá trên tiêu đề + khối đầu ruột mẫu | miễn phí |
| 3 | Mô hình đọc khối đầu, trả nhãn `ai điền` + nhóm nghiệp vụ | 1 lượt gọi/mẫu, có cache |

Tầng 2 chỉ kết luận khi CHẮC (một bên có điểm, bên kia bằng 0); mọi trường hợp lửng lơ
đẩy lên tầng 3. Kết quả bám theo `body_hash` nên mỗi mẫu chỉ tốn một lượt gọi mô hình
trong cả đời nó.

**Đăng bản dựng lại, không đăng HTML của TVPL.** Ruột biểu mẫu là phụ lục của văn bản
quy phạm — Điều 15 Luật Sở hữu trí tuệ loại khỏi đối tượng bảo hộ. Nhưng bản chuyển
đổi sang HTML là công sức của TVPL, nên HTML gốc chỉ ở lại `data/forms/html/` làm
nguyên liệu; thứ đăng ra ngoài là Markdown/DOCX/PDF dựng lại theo template nhà, luôn
kèm khối ghi nguồn và link ngược.

**DOCX là bản chính, PDF là bản phụ.** Biểu mẫu sinh ra để ĐIỀN; chỉ có PDF thì người
dùng vẫn phải sang TVPL tải bản Word.

**Biểu mẫu không có hiệu lực riêng — nó sống chết theo văn bản căn cứ.** TVPL không
công bố dữ kiện này, trang chỉ ghi "Cập nhật: <ngày>" tức ngày họ sửa trang. Hệ thống
suy hiệu lực từ căn cứ và **không bao giờ mặc định "còn hiệu lực"**:

| Cờ | Nghĩa |
|---|---|
| 🟢 `con_hieu_luc` | mọi căn cứ còn hiệu lực |
| 🟠 `co_ban_thay_the` | căn cứ đã bị thay thế/bãi bỏ — kèm số hiệu văn bản mới để đi tìm mẫu mới |
| 🟡 `can_kiem_tra` | căn cứ bị sửa đổi, hoặc hết hiệu lực một phần |
| 🔴 `het_hieu_luc` | căn cứ đã hết hiệu lực toàn bộ |
| ⚪ `khong_ro` | căn cứ chưa có trong kho — chưa xác minh được, KHÔNG phải "còn hiệu lực" |

Thứ tệ nhất thắng: mẫu có một căn cứ sống và một căn cứ chết là mẫu **đáng ngờ**.

Đo trên 219 mẫu ngày 19/08/2026: 4 mẫu có căn cứ đã hết hiệu lực, 2 mẫu có bản thay
thế, 23 mẫu cần kiểm tra. 189 mẫu chưa xác minh được vì kho văn bản chưa phủ hết căn
cứ — con số đó sẽ giảm khi kho lớn lên, và `src/main.py` bước 9 tự tính lại mỗi ngày.

Mẫu bị TVPL gỡ khỏi trang liệt kê được gắn `delisted_at` và cảnh báo riêng: nguồn đã
bỏ nó thì bản đã tải chỉ còn giá trị tra cứu, không nên dùng để nộp.

## Trang trợ lý pháp lý

Ứng dụng tĩnh riêng ở `/tro-ly/`, **thêm mới chứ không thay Quartz** — URL
`/van-ban/*` đã phát ra trong báo cáo PDF nên không được đổi.

Bố cục ba cột học từ [thuvien-vbpl-26.web.app](https://thuvien-vbpl-26.web.app):
nav lĩnh vực (navy) · danh mục (giấy) · nội dung (trắng), cộng panel nguồn trích
dẫn bên phải. Bảng màu navy `#1b3a5c` + son `#a1342c` + vàng `#c8a33c` + giấy
`#f5f1e8` là bảng màu tài liệu hành chính, không phải bảng màu SaaS.

**Hỏi đáp có trích dẫn kiểm chứng được.** Gọi `POST /chat` theo hợp đồng SSE của
[R2AI2026](https://github.com/…): `sub_queries → retrieval → context_ready →
tool_call → answer`. Mỗi số `[N]` trong câu trả lời là **thẻ bấm được** — bấm là mở
panel với đúng đoạn nguồn. Chưa cấu hình API thì chạy **chế độ thử**: tra trong kho
và trả về tài liệu khớp, KHÔNG gọi mô hình và KHÔNG bịa câu trả lời pháp lý.
Endpoint cấu hình ở nút ⚙️, lưu trong `localStorage`.

**Dữ liệu riêng, không dùng `contentIndex.json` của Quartz.** Đo ngày 19/08/2026:

| | thô | gzip | parse |
|---|---:|---:|---|
| `contentIndex.json` (Quartz) | 17,42 MB | 1,72 MB | 3 bên cùng parse |
| `tro-ly/du-lieu.json` | 1,50 MB | 0,28 MB | 1 lần |

77% của contentIndex là trường `content` — toàn văn từng trang, chỉ để tìm kiếm.
Bộ này chỉ mang metadata cần để lọc và tra.

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
| Telegram Bot Token | Điều khiển báo cáo, cảnh báo lỗi | @BotFather |
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

623 test, 1 bỏ qua. Nhiều test ghi lại **lỗi đã xảy ra thật** kèm số đo — đọc docstring
của chúng trước khi sửa phần liên quan.
