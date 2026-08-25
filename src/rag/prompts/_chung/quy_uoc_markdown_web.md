<!-- BẢN THAY THẾ cho _chung/quy_uoc_markdown.md, dùng riêng cho bài Cẩm nang
     đăng WEB. KHÔNG include file kia ở đây.

     VÌ SAO PHẢI TÁCH RA THAY VÌ DÙNG CHUNG: bản kia viết cho bộ dựng PDF
     (src/utils/report_pdf.py). Nó CẤM liên kết, và bắt tiêu đề chương ở bậc ba.
     Bê nguyên sang bài web thì ra một bài KHÔNG CÓ LIÊN KẾT NÀO — hỏng đúng
     phần SEO mà bài này tồn tại vì nó — và cấu trúc heading lệch một bậc so với
     bộ chuyển markdown bên nhận. -->

## QUY ƯỚC MARKDOWN (bài đăng web — bộ chuyển bên nhận phụ thuộc vào đây)

Bên nhận tự chuyển markdown → HTML rồi sanitize. Chỉ những thứ liệt kê dưới đây
được nhận; thứ khác lọt vào sẽ bị bỏ hoặc hiện thành chữ trần.

| Ý muốn | Viết như thế nào |
|---|---|
| Tiêu đề mục lớn | `## Tên mục` |
| Tiêu đề mục con | `### Tên mục con` (sâu hơn nữa: `####`) |
| Đoạn văn | Viết thẳng, mỗi đoạn một khối |
| Danh sách | `-` hoặc `*` hoặc `+`; đánh số thì `1.` |
| Bảng | `\| a \| b \|` kèm dòng ngăn `\|---\|---\|` |
| Nhấn mạnh | `**đậm**`, `*nghiêng*` |
| Trích dẫn / lưu ý | Bắt đầu dòng bằng `> ` |
| Mã, tên trường, ký hiệu | `` `mã` `` |
| Liên kết | `[chữ hiển thị](https://…)` hoặc `[chữ hiển thị](/duong-dan-noi-bo)` |

**KHÔNG dùng `#` một dấu thăng.** Bài đã có tiêu đề riêng ở trường `tieu_de`;
`#` trong thân bài bị hạ thành `##`, nên viết `##` ngay từ đầu cho khớp.

**KHÔNG viết HTML thô** (`<div>`, `<br>`, `<table>`…). Đầu ra mô hình là nguồn
không tin được nên bên nhận escape mọi thẻ — HTML thô sẽ hiện nguyên dạng thành
chữ giữa bài, không render.

**KHÔNG dùng khối mã ba dấu ``` bọc cả bài.** Bài là văn xuôi, không phải mã.

Không cần dòng trống ngăn giữa các khối: bộ chuyển phân loại theo từng dòng, nên
heading dính liền danh sách vẫn ra đúng cấu trúc. Vẫn nên để dòng trống cho dễ
đọc khi soát tay.

### Liên kết

Bộ chuyển bên nhận có hỗ trợ liên kết, nhưng **quyền dùng nó phụ thuộc dữ liệu
đầu vào, không phụ thuộc ý muốn của bạn**:

- **Dữ liệu đầu vào KHÔNG có mục liệt kê URL hay đường dẫn cho phép → viết bài
  KHÔNG CÓ MỘT LIÊN KẾT NÀO.** Đây là trường hợp mặc định. Không có link là
  đúng, không phải thiếu sót, và **không ai trừ điểm bài vì nó không có link**.
- Chỉ khi đầu vào đưa sẵn URL hoặc đường dẫn thì mới được dùng, và chỉ được dùng
  **đúng những địa chỉ đã được đưa**, chép nguyên văn.
- **Tuyệt đối không tự nghĩ ra URL.** Một liên kết bịa dẫn người đọc tới trang
  404 hoặc tới trang của người khác — tệ hơn hẳn việc không có liên kết. Quy tắc
  này giống hệt quy tắc cấm bịa số hiệu văn bản.
- Khi được phép dùng: link ngoài `https://…` tự gắn `rel="nofollow noopener"
  target="_blank"`; đường dẫn nội bộ bắt đầu bằng `/` được giữ nguyên; mọi scheme
  khác (`javascript:`, `data:`) bị bỏ và link hiện thành chữ trần. Tối đa 3–5
  liên kết một bài.
