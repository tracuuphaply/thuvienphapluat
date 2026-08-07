<!-- Dùng chung cho cả ba loại báo cáo. Bộ dựng PDF (src/utils/report_pdf.py)
     phụ thuộc trực tiếp vào quy ước này — đây KHÔNG phải gợi ý. -->

## 7. QUY ƯỚC MARKDOWN (bộ dựng PDF phụ thuộc vào đây)

| Ý muốn | Viết như thế nào |
|---|---|
| Tiêu đề chương | `### CHƯƠNG I — …` (ba dấu thăng) |
| Tiêu đề mục | `#### 1. Tên mục` (bốn dấu thăng) |
| Bảng | Bảng Markdown chuẩn, **luôn có dòng tiêu đề** |
| Nhấn mạnh | `**in đậm**` |
| Hộp nhận định | Bắt đầu dòng bằng `>` |
| Miễn trách nhiệm | Đặt dưới dòng chứa cụm "miễn trách nhiệm", hoặc viết dạng `>` |

Khối `>` được dựng thành hộp có nhãn, nhãn tự chọn theo nội dung. Gặp các cụm
"miễn trách", "chỉ mang tính chất tham khảo", "không thay thế" thì hộp mang nhãn
**TUYÊN BỐ MIỄN TRÁCH NHIỆM**; còn lại là **NHẬN ĐỊNH**. Không cần tự ghi nhãn.

Không dùng: ảnh, liên kết, HTML thô, khối mã. Biểu đồ do hệ thống chèn tự động,
**không tự vẽ biểu đồ bằng ký tự**.

**Không viết khối kêu gọi liên hệ, quảng bá dịch vụ hay đăng ký nhận bản tin.**
Báo cáo giữ đúng vai trò tài liệu pháp lý; phần mời gọi nằm ở nội dung email gửi
kèm, không nằm trong file PDF.
