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

### Liên kết — phần này là lý do bài tồn tại

- Link ngoài `https://…` được giữ và tự gắn `rel="nofollow noopener"
  target="_blank"`. Chỉ trỏ tới nguồn có thật mà bạn được cung cấp trong dữ liệu
  đầu vào; **không tự nghĩ ra URL**.
- Đường dẫn nội bộ bắt đầu bằng `/` được giữ nguyên và truyền PageRank. Chỉ dùng
  đường dẫn nội bộ khi dữ liệu đầu vào đưa sẵn cho bạn.
- Mọi scheme khác (`javascript:`, `data:`) bị bỏ, link hiện thành chữ trần.
- Trong một bài, **tối đa 3–5 liên kết**. Nhồi link không giúp gì cho người đọc.
