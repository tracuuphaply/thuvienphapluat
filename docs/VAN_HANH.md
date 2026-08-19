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

Quy trình phục hồi đã được kiểm chứng ngày 07/8/2026: giải nén `db_<ngày>.sqlite.gz`
ra thư mục tạm, `PRAGMA integrity_check` trả `ok`, số văn bản và số quan hệ khớp
bản đang chạy. Nên lặp lại định kỳ, và **bắt buộc chạy trước mỗi migration** đụng
vào bảng `documents`.

```bash
gunzip -c data/backups/db_2026-08-06.sqlite.gz > /tmp/restore_test.db
sqlite3 /tmp/restore_test.db "PRAGMA integrity_check; SELECT COUNT(*) FROM documents;"
```

## Nơi lưu trữ đám mây

Chọn bằng `CLOUD_DRIVE_PROVIDER` trong `.env`: `gdrive` | `lark` | `both`.
Trước đây đích lưu trữ được suy từ việc có hay không `LARK_APP_ID`, nên chỉ cần
điền khoá Lark là pipeline âm thầm đổi chỗ lưu file.

Văn bản kéo về do bị dẫn chiếu (`is_closure_node = 1`) **vẫn** được đẩy lên mây.
Bản cũ loại chúng ra; sai, vì văn bản đã bị bãi bỏ chính là thứ trả lời được
"quy định nào đã đổi", nên người đọc báo cáo phải mở được nó. Đặt
`UPLOAD_CLOSURE_NODES=false` nếu muốn Drive chỉ chứa văn bản nghiệp vụ.

### Thiết lập Google Drive lần đầu

Xác thực bằng **OAuth**, không dùng service account: Google cấp cho service
account hạn mức lưu trữ 0 GB nên upload vào My Drive luôn trả `403
storageQuotaExceeded` và không xin thêm quota được. Đó là lý do nhánh Drive cũ
chưa từng chạy và `run_daily.sh` luôn truyền `--skip-gdrive`.

Giao diện Google đã đổi: mục "OAuth consent screen" cũ nay là **Google Auth
Platform**, tách thành 4 tab Branding · Audience · Clients · Data Access. Màn
hình *"Google Auth Platform not configured yet"* ở lần đầu là bình thường.

1. [console.cloud.google.com](https://console.cloud.google.com) → tạo project.
2. **APIs & Services → Library** → bật **Google Drive API**.
3. **Google Auth Platform → Get started** → App name + email hỗ trợ → Audience
   **External** → email liên hệ → đồng ý policy → **Create**.
4. Tab **Data Access** → *Add or remove scopes* → chỉ tích
   `.../auth/drive.file` → Update → Save.
5. Tab **Audience** → **PUBLISH APP** → Confirm. Trạng thái phải là
   **In production**.
6. Tab **Clients** → *Create client* → **Desktop app** → Download JSON → lưu
   thành `credentials/gdrive_oauth_client.json`.
7. `python -m scripts.gdrive_check --authorize` → đăng nhập, bấm Allow. Màn hình
   "Google hasn't verified this app" là bình thường với scope không nhạy cảm →
   Advanced → Go to … (unsafe).
8. Script tự tạo thư mục gốc và in id ra; ghi vào `.env` thành
   `GDRIVE_ROOT_FOLDER_ID=...`, rồi đặt `CLOUD_DRIVE_PROVIDER=gdrive`.

**Hai cái bẫy, cả hai đều không lộ ra lúc test tay:**

- **Bỏ bước 5** → refresh token hết hạn sau đúng 7 ngày, pipeline chạy hằng ngày
  chết câm với lỗi `invalid_grant`. Google chỉ cấp 7 ngày cho ứng dụng còn ở
  trạng thái Testing.
- **Trỏ `GDRIVE_ROOT_FOLDER_ID` tới thư mục tạo tay** → mọi lần ghi báo lỗi, vì
  phạm vi `drive.file` chỉ cho ghi vào thư mục do chính ứng dụng tạo. Để trống
  biến này ở lần chạy đầu.

Khi thấy `invalid_grant` trong log, chạy lại `gdrive_check --authorize`.

### Hàng đợi upload

Upload hỏng dù chỉ một file cũng **không** đánh dấu `documents.cloud_synced_at`,
và văn bản được xếp vào bảng `upload_queue` để thử lại. Cột `cloud_synced_at` là
cổng: chưa có giá trị thì `AUTO_CLEANUP_LOCAL_FILES` không được phép xoá file
local — đánh dấu sớm là mất bản gốc mà trên mây cũng không có.

```sql
SELECT doc_num, provider, file_kinds, attempts, last_error FROM upload_queue;
```

Đẩy lại phần còn thiếu: `python -m src.main --upload-only`.

## Bao đóng dẫn chiếu

Kéo về mọi văn bản mà kho đang dẫn chiếu tới nhưng chưa có, **kể cả văn bản đã
hết hiệu lực hoặc bị bãi bỏ** — đó chính là thứ trả lời được "quy định nào đã
đổi và doanh nghiệp chịu ảnh hưởng ra sao".

```bash
python -m scripts.run_closure --max-fetch 400     # lặp tới khi "đang chờ" về 0
python -m src.main --sync-rag-only                # BẮT BUỘC sau mỗi đợt
```

Hàng đợi nằm trong bảng `crawl_frontier` nên ngắt giữa chừng rồi chạy lại là
tiếp đúng chỗ dừng.

### Trần độ sâu — cái van quan trọng nhất

`CLOSURE_MAX_DEPTH` (mặc định 0 = không giới hạn). **Nên đặt 2.**

Đo trên kho thật: không đặt trần thì mỗi văn bản kéo về sinh thêm **1,54** văn
bản cần kéo, tức không hội tụ. Van cắt hub (`CLOSURE_HUB_INDEGREE=200`) không
giúp gì — không văn bản nào trong hàng đợi vượt ngưỡng đó. Nguồn phân kỳ nằm ở
đầu ngược lại: **71% hàng đợi là văn bản chỉ bị dẫn chiếu đúng một lần**, mỗi
cái kéo về lại sinh ~7 dẫn chiếu mới. Đặt trần 2 kéo tỷ lệ xuống **1,06** và
cho bao đóng một điểm kết thúc xác định.

Mục vượt trần được đánh dấu `state = 'TOO_DEEP'` chứ không xoá, nên nâng trần
sau này là chạy tiếp chứ không phải dò lại từ đầu.

### Sau khi đổi trần: phải tính lại độ sâu

```bash
python -m scripts.backfill_closure_depth --dry-run
python -m scripts.backfill_closure_depth
```

Duyệt chiều rộng từ tập hạt giống để ra **đường ngắn nhất**. Bắt buộc chạy sau
khi nâng/hạ trần, vì trần chỉ có ý nghĩa khi độ sâu trong kho là đúng.

### Dung lượng

Đo được **1,57 MB/văn bản** (gồm HTML gốc, clean text, chunk, index RAG). Chốt
chặn `MIN_FREE_DISK_GB` dừng bao đóng trước khi đầy đĩa. Đừng đưa về 0: đầy ổ
khởi động thì SQLite ghi hỏng giữa transaction.

## Kho biểu mẫu

Làm mới hằng tuần bằng `scripts/run_weekly_forms.sh` (launchd agent
`vn.legalvault.weeklyforms`, Chủ nhật 5h). Bốn bước, đúng thứ tự:

```bash
python -m scripts.crawl_forms --source hopdong --chi-hang-doi   # nạp hàng đợi
python -m scripts.crawl_forms --source hopdong --tiep-tuc       # tải chi tiết
python -m scripts.crawl_forms --source bieumau --chi-hang-doi
python -m scripts.crawl_forms --source bieumau --tiep-tuc
python -m scripts.classify_forms                  # phễu 3 tầng
python -m scripts.build_forms                     # dựng DOCX + PDF
python -m scripts.upload_forms_gdrive             # đưa bản .docx lên Drive
```

Phân loại trước, dựng file sau — dựng cho cả kho rồi mới biết phần lớn là báo cáo
nội bộ của cơ quan nhà nước thì đã đốt công vô ích.

### Đưa biểu mẫu lên Drive

`upload_forms_gdrive` chỉ tải bản **.docx**, không tải .pdf. Bản Word là bản điền
được — thứ người ta thật sự cần ở một biểu mẫu; đo trên 653 mẫu thì docx 24 MB
còn pdf 74 MB, tức gấp bốn dung lượng để thêm một thứ đã có đường lấy khác (bản
PDF vẫn tải trực tiếp từ trang công khai).

Chạy lại được: mẫu nào đã có `gdrive_docx_link` thì bỏ qua, và kho được ghi theo
từng lô 20 mẫu chứ không đợi hết.

**Nếu thấy báo `DỪNG SỚM`** thì đó là Drive chặn theo hạn mức ghi, không phải lỗi
file. Đo lần chạy đầu ngày 19/08/2026: 256 lượt trót lọt rồi 394 lượt hỏng liên
tiếp. Chờ vài phút rồi chạy lại lệnh đó, nó tiếp từ chỗ dừng.

Liên kết ghi vào kho được dựng lại từ ID file (`drive.google.com/file/d/<ID>/view`)
chứ **không** dùng `webViewLink` mà Drive trả về: chuỗi đó chứa `ouid=…`, tức mã
tài khoản Google của người tải lên, và trang công khai thì ai cũng đọc được.

### Vì sao tách hai pha `--chi-hang-doi` rồi `--tiep-tuc`

Giai đoạn liệt kê tốn ~40 lượt tải và 5,5 phút cho kho hợp đồng, và nó chạy TRƯỚC
việc cần làm. Đo ngày 18/08/2026, ba lượt liền:

| Cách chạy | Kết quả |
|---|---|
| Một lượt (liệt kê rồi tải chi tiết) | 0 mẫu mới, bị chặn 5 lần rồi dừng |
| Thử tay một trang chi tiết ngay sau đó | THÔNG, 58 KB |
| `--chi-hang-doi` rồi `--tiep-tuc` | chạy liên tục, **0 lần bị chặn** |

Nghĩa là 40 lượt liệt kê làm Cloudflare dựng lại thử thách trước khi bộ cào kịp
làm việc gì có ích. Hàng đợi nằm trong bảng `legal_forms` (trạng thái `PENDING`)
nên chỉ cần liệt kê MỘT lần, sau đó `--tiep-tuc` dùng trọn `cf_clearance` còn tươi
cho đúng việc tải trang chi tiết.

### Bị Cloudflare chặn giữa chừng

Bộ cào tự dừng sau 5 lần chặn liên tiếp (`MAX_BLOCKED_STREAK`) thay vì đốt hết
danh sách — đo ngày 18/08/2026: bản không có cầu dao đã ghi ~600 dòng `FAILED`
trong 40 phút mà không lấy được gì.

Chạy lại chính lệnh đó để đi tiếp: trang đã tải nằm ở `data/forms/html/` và được
**bóc lại từ đĩa**, không tải lại TVPL.

**TĂNG `TVPL_RATE_LIMIT_SECONDS` KHÔNG GIẢI QUYẾT ĐƯỢC.** Đo ngày 18/08/2026,
xen kẽ trong cùng một phiên ở cùng tốc độ 5 giây:

| Loại trang | Kết quả |
|---|---|
| `/hopdong?type=6` (liệt kê) | THÔNG, 204 KB |
| `/hopdong/249/…` (chi tiết) | CHẶN |
| `/hopdong?type=7` (liệt kê) | THÔNG, 207 KB |
| `/hopdong/226/…` (chi tiết) | CHẶN |

TVPL đặt bảo vệ mạnh hơn hẳn cho **trang chi tiết**. Trang bị chặn trả về đúng
thử thách Cloudflare (`Chờ một chút…`, "Thực hiện xác minh bảo mật", có Ray ID),
và nó **không tự giải kể cả sau 120 giây** — `_goto()` chỉ chờ 15 giây nhưng chờ
lâu hơn cũng vô ích, đã đo.

Cách sửa thật, theo thứ tự nên thử:

1. **Giải thử thách bằng tay một lần trong chính Chrome của pipeline.** Chế độ
   CDP mở Chrome bằng hồ sơ riêng ở `data/chrome_profile/`, và cookie
   `cf_clearance` lấy được sẽ nằm lại đó cho các lần chạy sau. Mở hồ sơ đó, vào
   một trang chi tiết bất kỳ, qua thử thách, rồi chạy lại lệnh cào.
2. **Xuất lại cookie ra `data/tvpl_cookies.json`** từ trình duyệt thật đã qua
   thử thách (xem HUONG_DAN_CHUYEN_GIAO §2.5). Lưu ý `cf_clearance` gắn với IP +
   User-Agent nên phải xuất từ chính máy sẽ chạy pipeline.
3. **Nghỉ vài giờ.** Phiên sáng cùng ngày đã tải trót lọt 67 trang chi tiết trước
   khi bị chặn, nên trạng thái này không vĩnh viễn.

Agent hằng tuần cứ chạy: mỗi lượt lấy thêm được phần nào thì kho đầy thêm phần
đó, và phần đã có không bị tải lại.

### Xem tình trạng kho

```bash
sqlite3 data/legal_docs.db \
  "SELECT crawl_status, COUNT(*) FROM legal_forms GROUP BY 1;
   SELECT audience, is_business, COUNT(*) FROM legal_forms GROUP BY 1,2;"
```

`crawl_status = EMPTY_BODY` nghĩa là trang tải được nhưng ruột mẫu rỗng — thường là
dấu hiệu TVPL đổi markup. Chạy `python -m pytest tests/test_form_parse.py` để xác
nhận: fixture ở `tests/fixtures/forms/` là bản sao trang thật, nếu test vẫn xanh mà
kho vẫn rỗng thì markup mới khác fixture, cần lưu fixture mới.

### Sửa bộ bóc rồi chạy lại mà không đụng TVPL

HTML gốc nằm ở `data/forms/html/{form_key}.html`. `crawl_forms` bóc lại từ đó khi
file đã có, nên sửa `src/sources/tvpl_forms_parse.py` rồi chạy lại là đủ. Dùng
`--lam-lai` khi thật sự cần tải lại từ TVPL.

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
