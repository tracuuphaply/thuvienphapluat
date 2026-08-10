# Hai việc cần bạn tự làm

Hai việc này tôi không làm thay được: một cần tài khoản GitHub của bạn, một cần
quyền quản trị trên Google Cloud của bạn.

Việc **B** gấp hơn — bỏ qua nó thì sau đúng 7 ngày Drive ngừng nhận file mà
không báo gì.

---

## A · Đưa trang tra cứu công khai lên GitHub Pages

### Nó để làm gì

Mỗi báo cáo PDF trích dẫn hàng chục số hiệu văn bản. Người đọc muốn kiểm chứng
thì cần bấm vào số hiệu và thấy văn bản gốc. Trang này là đích của những link đó.

Hiện `PUBLIC_VAULT_BASE_URL` để trống nên **PDF không phát link nào** — có chủ ý:
một báo cáo trỏ tới 404 làm người đọc nghi ngờ cả những phần đúng.

Nội dung đã sinh sẵn: **4.879 trang, 27 MB**, nằm ở `build/public-vault/content`.

### Vì sao phải là repo RIÊNG

Đừng bật GitHub Pages trên repo `thuvienphapluat`.

Repo đó chứa `.env` với khoá API thật, thư mục `credentials/` với token Google,
và `data/chrome_profile/` có cookie đăng nhập TVPL. Công khai repo đồng nghĩa
công khai **toàn bộ lịch sử git** — và commit `a3dd597` đã từng phải gỡ một
profile Chrome 160 MiB kèm file Cookies khỏi lịch sử nhánh. Xoá file ở commit
mới không xoá nó khỏi lịch sử.

Repo riêng chỉ chứa nội dung sinh ra thì không có gì để rò.

### Các bước

**1. Tạo repo công khai trên GitHub**

Vào github.com → New repository → tên `legal-vault-public` → chọn **Public** →
không tích thêm README/`.gitignore` gì cả.

**2. Dựng repo trên máy**

```bash
cd ~/Downloads
git clone https://github.com/jackyzha0/quartz.git legal-vault-public
cd legal-vault-public
rm -rf .git && git init
npm install
```

**3. Chép nội dung đã sinh sẵn vào**

```bash
DU=~/Downloads/thuvienphapluat/build/public-vault
rm -rf content
cp -r "$DU/content" .
cp "$DU/quartz.config.ts" .
mkdir -p .github/workflows
cp "$DU/.github/workflows/build.yml" .github/workflows/
```

**4. Sửa một dòng trong `quartz.config.ts`**

Tìm `baseUrl` và đổi thành tên GitHub của bạn:

```ts
baseUrl: "TEN_GITHUB_CUA_BAN.github.io/legal-vault-public",
```

**5. Xem thử trên máy trước khi đẩy lên**

```bash
npx quartz build --serve
```

Mở http://localhost:8080. Cần thấy: trang chủ có mục lục theo lĩnh vực, bấm vào
một văn bản ra trang dữ kiện, và **sơ đồ quan hệ** (graph view) hiện các văn bản
dẫn chiếu lẫn nhau. Không thấy sơ đồ nghĩa là wikilink chưa phân giải — báo tôi.

**6. Đẩy lên**

```bash
git add -A
git commit -m "Kho tra cứu văn bản pháp luật"
git branch -M main
git remote add origin https://github.com/TEN_GITHUB_CUA_BAN/legal-vault-public.git
git push -u origin main
```

**7. Bật GitHub Pages**

Repo `legal-vault-public` → **Settings** → **Pages** → mục *Source* chọn
**GitHub Actions**. Đợi tab Actions chạy xong (khoảng 2–4 phút với 4.879 trang).

**8. Báo lại địa chỉ cho hệ thống**

Thêm vào `.env` của repo `thuvienphapluat`:

```
PUBLIC_VAULT_BASE_URL=https://TEN_GITHUB_CUA_BAN.github.io/legal-vault-public
```

Từ lúc này PDF bắt đầu phát link kiểm chứng. Chỉ những văn bản đã thực sự đăng
mới được phát link — văn bản chưa đăng vẫn để chữ trơn.

### Cập nhật về sau

Nội dung sinh lại bằng `python -m scripts.publish_site`, rồi chép `content/` sang
repo công khai và push. Chỉ trang có nội dung đổi mới được ghi lại, nên lần sau
nhanh hơn nhiều.

---

## B · Chuyển Google Auth Platform sang "In production"

### Vì sao gấp

Màn hình chấp thuận OAuth đang ở trạng thái **Testing** thì Google cho refresh
token hết hạn sau **đúng 7 ngày**, trả lỗi `invalid_grant`.

Hệ quả: pipeline chạy 6h sáng mỗi ngày sẽ ngừng đẩy file lên Drive, và vì nó
chạy tự động nên bạn chỉ phát hiện khi thấy Drive không có văn bản mới.

Đổi sang Production **không cần Google thẩm định** — hệ thống chỉ xin phạm vi
`drive.file`, là phạm vi không nhạy cảm. Chỉ là một nút bấm.

### Các bước

1. Vào [console.cloud.google.com](https://console.cloud.google.com), chọn đúng
   project đã tạo (tên bạn đặt lúc đầu, ví dụ `nao-phap-luat`).

2. Menu trái → **APIs & Services** → **Google Auth Platform**.

3. Tab **Audience**. Nhìn mục *Publishing status*:
   - Hiện **"In production"** → xong, không phải làm gì.
   - Hiện **"Testing"** → bấm **PUBLISH APP** → **Confirm**.

4. Tab **Data Access**. Kiểm danh sách phạm vi chỉ có đúng một dòng:
   ```
   .../auth/drive.file
   ```
   Nếu có thêm `.../auth/drive` (không có `.file`) thì **xoá đi**. Phạm vi đó
   thuộc diện hạn chế, phải qua đánh giá an ninh CASA — mất nhiều tuần và tốn
   tiền, mà hệ thống không cần tới nó.

### Kiểm lại

```bash
cd ~/Downloads/thuvienphapluat
.venv/bin/python -m scripts.gdrive_check
```

Phải thấy xác thực thành công và upload thử được. Nếu ra `invalid_grant` thì
token đã hết hạn — cấp lại một lần:

```bash
.venv/bin/python -m scripts.gdrive_check --authorize
```

Màn hình *"Google hasn't verified this app"* là bình thường với phạm vi không
nhạy cảm → **Advanced** → **Go to … (unsafe)**.

### Lưu ý dài hạn

Sau khi publish, refresh token không tự hết hạn nữa. Nhưng nó vẫn mất hiệu lực
nếu bạn đổi mật khẩu tài khoản Google, thu hồi quyền thủ công, hoặc **không dùng
suốt 6 tháng**. Hệ thống bắt lỗi `invalid_grant` và gửi cảnh báo Telegram kèm
câu lệnh cần chạy, nên nó không chìm trong log.
