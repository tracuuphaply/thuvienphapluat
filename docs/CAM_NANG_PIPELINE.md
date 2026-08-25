# Pipeline sinh bài Cẩm nang — nối sang `thongtincty`

Repo này **sinh nội dung**; repo `ThongtinCty/thongtincty` **xuất bản**. Hai bên
gặp nhau qua đúng một file JSON và không chia sẻ gì khác.

```
tracuuphaply (nửa A — sinh nội dung)              thongtincty (nửa B — xuất bản)
  legal-vault-public   (kho biểu mẫu)  ─┐
  thuvienphapluat      (prompt + cổng) ─┴─► bai.json ─► npm run import:phapluat
```

Vì sao chia hai: session Claude Code khoá theo **chủ sở hữu repo**. Session mở
trên `thongtincty` không add được repo của `tracuuphaply` và ngược lại — nhưng
giới hạn tính theo CHỦ, nên bên này add thêm được `legal-vault-public`. Nghĩa là
bên này nắm đủ cả kho dữ liệu lẫn thư viện prompt để làm trọn khâu sinh nội dung.

---

## 1. Chạy

Cần một checkout `legal-vault-public` — chính thứ bên xuất bản cũng nạp.

```bash
git clone https://github.com/tracuuphaply/legal-vault-public ../legal-vault-public

# đối chiếu kho, KHÔNG gọi mô hình, không tốn tiền
python -m scripts.sinh_cam_nang --vault ../legal-vault-public --soi

# sinh thử 3 bài
python -m scripts.sinh_cam_nang --vault ../legal-vault-public --limit 3

# nhóm viết được bài sâu nhất: có căn cứ khớp kho + có toàn văn trên Drive
python -m scripts.sinh_cam_nang --vault ../legal-vault-public \
    --co-toan-van --limit 20 --out bai.json
```

Rồi bên `thongtincty` (nơi giữ `.env.local` với service key):

```bash
npm run import:phapluat -- --dir <legal-vault-public> --generated bai.json
```

### Toàn bộ cờ

| Cờ | Việc |
|---|---|
| `--vault <path>` | Gốc checkout `legal-vault-public` (**bắt buộc**) |
| `--soi` | Đối chiếu kho và in bảng, KHÔNG gọi mô hình |
| `--out <file>` | File JSON đầu ra (mặc định `bai.json`) |
| `--limit <n>` | Số bài tối đa một lượt (mặc định **20**) |
| `--co-toan-van` | Chỉ biểu mẫu có căn cứ kèm toàn văn trên Drive |
| `--nghiep-vu <mã>` | Lọc theo nhóm nghiệp vụ, vd `hop_dong` |
| `--hieu-luc <mã>` | Lọc theo cờ hiệu lực, vd `con_hieu_luc` |
| `--form-key <k>` | Chỉ sinh cho `form_key` này (lặp lại được) |
| `--tat-ca` | Sinh lại cả biểu mẫu nguồn chưa đổi (**tốn tiền**) |
| `--khong-toan-van` | Không tải toàn văn từ Drive — bài sẽ nông hơn |
| `--trang-thai <file>` | Sổ `da-sinh.json` (mặc định `cam-nang/da-sinh.json`) |
| `--db <file>` | SQLite đối chiếu trích dẫn. Bỏ trống = dựng từ chỉ mục vault |
| `--model <tên>` | Ghi đè `CAM_NANG_MODEL` |

### Biến môi trường

| Biến | Mặc định | Việc |
|---|---|---|
| `V98_API_KEY` / `OPENAI_API_KEY` | — | Khoá gọi mô hình. Thiếu là dừng ngay, không sinh bài rỗng |
| `OPENAI_API_BASE` | `https://cheapkeyai.shop/v1` | Gateway tương thích OpenAI |
| `CAM_NANG_MODEL` | `REPORT_MODEL` | Model sinh thân bài |
| `CAM_NANG_MAX_TOKENS` | `8000` | Trần token một bài |

---

## 2. Hợp đồng dữ liệu — chỉ bốn trường

`bai.json` là **một mảng** bản ghi. Mỗi bản ghi đúng bốn trường nội dung, cộng
cờ do cổng ghi:

```jsonc
[
  {
    "form_key":    "hopdong-101",   // = trường `k` trong du-lieu.json
    "tieu_de":     "Hợp đồng làm gia sư: 7 chỗ hở cần vá trước khi ký",
    "mo_ta":       "Mẫu hợp đồng gia sư không có căn cứ pháp lý bắt buộc…",
    "than_bai":    "## Vì sao…\n\nNội dung markdown…",
    "citation_ok": true
  }
]
```

| Trường | Ràng buộc | Bên B làm gì với nó |
|---|---|---|
| `form_key` | bắt buộc, khớp `k` trong `du-lieu.json` | Khoá nối + `import_key`. Không khớp kho → bị báo và bỏ |
| `tieu_de` | bắt buộc, 3–200 ký tự | Thành `title` |
| `mo_ta` | ≤ 500 ký tự | Thành `excerpt` → meta description |
| `than_bai` | markdown | Thành thân bài, sau khi sanitize |
| `citation_ok` | **phải là `true`** | Cổng kiểm trích dẫn |

### Bốn thứ bên B TỰ DỰNG — pipeline này không sinh trùng

Đây là chốt chặn cho bốn lỗi đã làm hỏng 653 bài lần trước. Thứ tự HTML cuối
cùng: `hộp hiệu lực` → `than_bai` → `ruột mẫu (gập)` → `footer`.

| Thứ | Bên B lấy từ đâu |
|---|---|
| **Slug** `/cam-nang/<slug>` | Trường `s` (fallback `k`) của `du-lieu.json` |
| **Chủ đề** | `v` (nghiệp vụ) → nhãn |
| **Hộp hiệu lực** | `e` + `c` + đồ thị `do_thi` |
| **Ruột biểu mẫu** | Mục `## Nội dung biểu mẫu` của file `.md`, đặt trong khối gập cuối bài |
| **Footer nguồn + miễn trừ** | Bên B dựng |

Mẫu prompt (`src/rag/prompts/prompt_cam_nang_bieu_mau.md` §2) nói lại đúng danh
sách này cho mô hình, kèm lệnh **không mở bài bằng "Tình trạng hiệu lực:…"** và
**không chép lại tờ mẫu**.

---

## 3. Ba cổng chặn

Cả ba chạy **trước khi ghi file**. Bên B cũng chặn, nhưng ở đó bài đã tốn một
lượt gọi mô hình rồi mới bị loại.

### Cổng tiêu đề (`cong_tieu_de`)

Từ chối tiêu đề mang dấu hiệu lấy từ ruột tờ mẫu. So khớp trên chuỗi đã bỏ dấu
nên mọi biến thể `HÒA`/`HOÀ`/NFD/thừa dấu chấm đều bị bắt:

- `CỘNG HOÀ [XÃ HỘI] [CHỦ NGHĨA] VIỆT NAM` · `Độc lập - Tự do…`
- `Mẫu số …` · `Phụ lục …` · `Biểu mẫu số …`
- `Đơn vị: …` · `Tên cơ quan/đơn vị …`

Hai dấu hiệu cuối neo vào **dấu hai chấm**, không phải cụm từ trần — nếu không
thì mọi tiêu đề có chữ "đơn vị" (`đơn vị tính`, `đơn vị thi công`) đều bị loại oan.

Trượt cổng này thì **sinh lại đúng một lượt** kèm chỉ dẫn sửa lỗi. Trượt lần hai
là bỏ biểu mẫu đó.

### Cổng hợp đồng (`cong_hop_dong`)

Kiểm đủ trường, đúng độ dài, và `citation_ok is True`. **Thiếu cờ cũng trượt** —
thiếu cờ nghĩa là cổng chưa chạy, không phải "đã qua".

Trần `than_bai` là **60.000 ký tự**, thấp hơn hẳn trần 200.000 ký tự mà bên B
đặt cho toàn bộ HTML một bài — phần chênh để dành cho ruột mẫu, hộp hiệu lực và
footer. Bài đúng chuẩn 900–1.600 chữ chỉ khoảng 6–12 KB; chạm trần nghĩa là mô
hình đang chép tờ mẫu hoặc lặp, và cả hai phải bị loại chứ không phải cắt bớt.

### Cổng trích dẫn (`cong_trich_dan`)

Gọi `src/rag/citation_check.py::check_citations()` cho từng bài rồi ghi kết quả
**thật** vào `citation_ok`. Nhóm `extra_allowed` được dựng **từ nguồn** — căn cứ
trong kho, toàn văn văn bản căn cứ, ruột tờ mẫu — và không bao giờ từ đầu ra mô
hình; dựng từ đầu ra thì mọi số bịa tự bảo chứng cho chính nó.

Kho đối chiếu mặc định **dựng từ chính chỉ mục vault** (`db_so_hieu_tu_kho`).
`data/legal_docs.db` cố ý không nằm trong git nên trên CI nó không tồn tại, và
chỉ mục vault chính là tập văn bản mà bên xuất bản có trang để dẫn tới. Dùng
`--db` trỏ tới DB thật của repo làm việc thì cổng **nới rộng** ra, không xiết vào.

---

## 4. Chọn biểu mẫu nào trước

653 biểu mẫu, tất cả nghiệp vụ `hop_dong`. Phân bố hiệu lực: `khong_ro` 481
(74%), `het_hieu_luc` 55, `co_ban_thay_the` 46, `can_kiem_tra` 39,
`con_hieu_luc` 32.

`chon_ung_vien()` chấm điểm: mỗi căn cứ có toàn văn 4 điểm, mỗi căn cứ khớp kho
2 điểm, hiệu lực rõ ràng 1 điểm. Biểu mẫu **đã bị nguồn gỡ** và biểu mẫu **không
có ruột mẫu** bị loại hẳn — hướng dẫn cho một tờ giấy không còn tồn tại ở đâu thì
tệ hơn không viết gì.

Bắt đầu từ **172 biểu mẫu có căn cứ khớp kho + có toàn văn trên Drive**
(`--co-toan-van`). Đừng chạy cả 653 ngay.

**Trần sản lượng: ≤ ~150 bài/tháng cho toàn hệ thống**, gồm cả bài auto-content;
Cẩm nang nên chiếm phần nhỏ trong đó. `--limit` mặc định 20 là cố ý. Chất > lượng:
một máy in bài chạy vô nghĩa chính là scaled content.

### Khuôn `khong_ro` (74%) — tông giọng riêng

Không có căn cứ thì §4 của mẫu prompt bắt: thừa nhận thẳng bằng một câu lời
thường, **không trích Điều luật nào**, không viết mục "Nộp ở đâu", và giá trị của
bài nằm ở việc soi chính tờ mẫu — điều khoản nào bất lợi cho bên nào, chỗ nào bỏ
trống thì tranh chấp về sau. Pipeline tự phát hiện nhóm này và chèn khối cảnh
báo tương ứng vào ngữ cảnh (`dung_ngu_canh`).

---

## 5. Chạy lại — chỉ sinh lại thứ đã đổi

Chạy lại toàn bộ **không hỏng gì** bên xuất bản: `import_key` = `form_key` nên
ánh xạ đúng một bài; bài đã xuất bản không bị ghi đè (trừ `--update-published`);
slug không đổi khi tiêu đề đổi. Nhưng sinh lại thân bài bằng LLM thì **tốn tiền**.

Sổ `cam-nang/da-sinh.json` giữ vân tay nguồn:

```jsonc
{
  "hopdong-101": {
    "nguon_hash": "sha256 của (tiêu đề + hiệu lực + căn cứ + ruột mẫu)",
    "sinh_luc":   "2026-08-24T10:00:00Z",
    "citation_ok": true
  }
}
```

Hash **phải gồm cả hiệu lực và căn cứ**, không chỉ ruột mẫu — văn bản căn cứ hết
hiệu lực là lý do chính đáng nhất để viết lại bài, mà ruột tờ mẫu thì không đổi
một ký tự nào khi điều đó xảy ra.

Bài `citation_ok: false` **cũng được sinh lại**: nó chưa bao giờ tới được bên
xuất bản (bị loại vĩnh viễn ở đó), nên coi nó là "đã có" thì biểu mẫu ấy vĩnh
viễn không có bài mà không ai thấy.

---

## 6. Tự động hoá — `.github/workflows/cam-nang.yml`

Chạy hằng tuần (02:00 UTC thứ Hai = 09:00 giờ Việt Nam), hoặc bấm tay qua
`workflow_dispatch`. Nó checkout thêm `legal-vault-public`, chạy pipeline, rồi
đẩy `bai.json` lên **release asset**.

Secrets phải khai trong repo:

| Secret | Việc |
|---|---|
| `VAULT_READ_TOKEN` | Fine-grained PAT đọc `tracuuphaply/legal-vault-public`. **Không dùng `GITHUB_TOKEN` mặc định** — nó chỉ có quyền trong repo đang chạy |
| `V98_API_KEY` hoặc `OPENAI_API_KEY` | Khoá gọi mô hình |
| `OPENAI_API_BASE` | (tuỳ chọn) gateway khác mặc định |

Nửa B chạy ở repo `thongtincty` hoặc chạy tay: tải asset mới nhất rồi
`npm run import:phapluat -- --dir <vault> --generated bai.json`. Bước đó cần
`SUPABASE_SERVICE_ROLE_KEY` nên phải ở nơi giữ được secret ấy.

**Đừng tự động hoá bước xuất bản.** Bộ nhập tạo bài `status='draft'` và không
bao giờ tự xuất bản; admin duyệt ở `/admin/cam-nang` (lọc "Nháp") rồi mới bấm
Xuất bản. Đó là chốt chặn cuối giữa "có nội dung" và "đăng nội dung sai lên
trang public", và nó phải là người.

---

## 7. Tái dùng gì — không viết lại

| File | Dùng để |
|---|---|
| `src/rag/prompts/_chung/giong_van_doanh_nghiep.md` | **Include nguyên** |
| `src/rag/prompts/_chung/dieu_cam_va_checklist.md` | **Include nguyên**, kèm một mục điều chỉnh riêng cho bài web |
| `src/rag/prompts/_chung/quy_uoc_markdown_web.md` | **Bản thay thế** cho bản PDF — xem dưới |
| `src/rag/reports/prompts.py` | `load_cam_nang_prompt()` + cơ chế `{{include:}}` |
| `src/rag/reports/llm.py` | `call_report_llm()` — retry 3 lần, xử lý `finish_reason == "length"` |
| `src/rag/citation_check.py` | Cổng bắt buộc §3 |
| `src/pipeline/text_processor.py` | `html_to_clean_text()` cho toàn văn tải từ Drive |

### ⚠ `quy_uoc_markdown.md` PHẢI THAY, không include

Bản đó viết cho bộ dựng PDF (`src/utils/report_pdf.py`): nó **cấm liên kết** và
bắt tiêu đề chương ở bậc ba (`### CHƯƠNG I`). Bê nguyên sang bài web thì ra một
bài **không có liên kết nào** — hỏng đúng phần SEO mà bài này tồn tại vì nó — và
cấu trúc heading lệch một bậc so với bộ chuyển markdown bên nhận.

Bản web (`quy_uoc_markdown_web.md`) cho phép `[chữ](url)`, gắn `rel="nofollow
noopener"` cho link ngoài, giữ nguyên đường dẫn nội bộ bắt đầu bằng `/`, và cấm
HTML thô (đầu ra mô hình là nguồn không tin được — HTML thô bị escape thành chữ).

---

## 8. Chỗ đã biết là chưa xong

**Trường `g` của biểu mẫu bị dùng cho hai việc.** Trong
`src/publish/assistant_export.py`, `g = 1` nghĩa là "nguồn đã gỡ biểu mẫu",
nhưng `g = "<id>"` nghĩa là "ID file .docx trên Drive" — bản ghi nào có cả hai
thì ID ghi đè cờ gỡ và cờ gỡ mất im lặng. Pipeline này đọc phòng thủ theo KIỂU
giá trị (`_drive_id_bieu_mau`), nhưng biểu mẫu vừa bị gỡ vừa có file Drive vẫn
lọt qua bộ lọc. Sửa tận gốc là đổi định dạng `du-lieu.json`, mà trang trợ lý
tĩnh đang đọc định dạng đó — phải bàn riêng.

**`--vault-base` và link số hiệu.** Cờ đó bên B sinh link `/van-ban/{slug}` cho
mỗi số hiệu, nhưng route ấy **không có** trong app `thongtincty` — nó thuộc site
kho bên `tracuuphaply`. Ba hướng, chưa chốt:

1. Bỏ trống `--vault-base` → số hiệu hiện dạng chữ. An toàn, mất phần link.
2. Trỏ ra site kho thật → hữu ích cho người đọc, nhưng là outbound link kèm `nofollow`.
3. Dựng trang `/van-ban/<slug>` trên chính `thongtincty` → mới thành internal
   link SEO thật, nhưng là một page type mới, phải bàn riêng.

Cho tới khi chốt, khuyến nghị chạy **không** `--vault-base` (hướng 1).
