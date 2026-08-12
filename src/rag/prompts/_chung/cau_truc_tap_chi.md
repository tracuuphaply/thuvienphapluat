<!-- Dùng chung cho cả ba loại báo cáo. Bộ dựng PDF (src/utils/report_pdf.py)
     nhận diện "BẢNG n:", "HÌNH n:" và "Nguồn:" để dựng dải tiêu đề và dòng
     nguồn — đây KHÔNG phải gợi ý trình bày. -->

## BỐ CỤC KIỂU TẠP CHÍ KHOA HỌC

Báo cáo trình bày theo khung của tạp chí nghiên cứu: có tóm tắt đứng đầu, các
phần đánh số, bảng và hình được đánh số và ghi nguồn, danh mục căn cứ ở cuối.

**Đây là quy tắc về BỐ CỤC, không phải về giọng văn.** Bên trong mỗi phần vẫn
viết theo quy tắc ở mục VĂN PHONG — câu ngắn, xưng "bạn", thay thuật ngữ bằng
lời thường. Khung học thuật để người đọc tìm được thứ họ cần và kiểm chứng
được; nó không phải cái cớ để viết khó hiểu.

### Khối mở đầu — bắt buộc, đặt trước mọi phần khác

```
**Tóm tắt.** Một đoạn 150–200 chữ: báo cáo rà soát cái gì, trong phạm vi nào,
tìm ra điều gì đáng chú ý nhất, và doanh nghiệp cần làm gì. Viết thành đoạn văn
liền mạch, không gạch đầu dòng. Người chỉ đọc đoạn này phải nắm được kết luận.

**Từ khoá:** 4–6 cụm, phân cách bằng dấu phẩy, chữ thường.

**Phạm vi và thời điểm.** Số văn bản đã rà, khoảng thời gian, ngày chốt dữ liệu.
```

KHÔNG viết tóm tắt tiếng Anh, KHÔNG đặt giả thuyết nghiên cứu H1/H2/H3, KHÔNG
bịa ngày nhận bài hay ngày duyệt đăng. Đây là báo cáo rà soát pháp lý, không
phải bài báo kiểm định giả thuyết — chép nguyên những mục đó vào là làm ra thứ
trông giống nghiên cứu nhưng rỗng.

### Đánh số phần

Các phần cấp một đánh số bằng chữ số La Mã và viết hoa toàn bộ:

```
### I. GIỚI THIỆU
### II. PHẠM VI RÀ SOÁT VÀ NGUỒN DỮ LIỆU
### III. KẾT QUẢ RÀ SOÁT
### IV. KẾT LUẬN VÀ KHUYẾN NGHỊ
```

Mục con dùng `#### 1. Tên mục`, đánh số liên tục trong từng phần.

### Bảng và hình — đánh số, có tiêu đề, có nguồn

Mỗi bảng phải có **dòng tiêu đề đứng ngay trên bảng** và **dòng nguồn ngay
dưới**, đúng ba dạng sau:

```
BẢNG 1: TÌNH TRẠNG HIỆU LỰC CỦA VĂN BẢN TRONG PHẠM VI RÀ SOÁT

| Số hiệu | Tên văn bản | Còn áp dụng không |
|---|---|---|
| … | … | … |

Nguồn: Cơ sở dữ liệu văn bản quy phạm pháp luật, chốt ngày {{NGAY_CHOT}}
```

Đánh số **liên tục từ 1** trong toàn báo cáo, riêng cho BẢNG và riêng cho HÌNH.
Tiêu đề bảng viết HOA TOÀN BỘ. Mọi bảng đều phải có dòng `Nguồn:` — một con số
không nói rõ lấy từ đâu thì không kiểm chứng được, và đó là điểm khác nhau giữa
báo cáo và ý kiến.

**Không tự đánh số HÌNH.** Biểu đồ do hệ thống chèn và tự đánh số; bạn chỉ được
nhắc tới chúng bằng chữ ("xem biểu đồ bên dưới") nếu thật sự cần.

### Danh mục căn cứ ở cuối

Phần cuối cùng luôn là:

```
### TÀI LIỆU VÀ CĂN CỨ PHÁP LÝ
```

Đánh số thứ tự, mỗi dòng một văn bản, theo mẫu:

```
1. Quốc hội (2025). Luật Doanh nghiệp, số 72/2025/QH15, ban hành ngày 20/6/2025.
2. Chính phủ (2026). Nghị định số 292/2026/NĐ-CP, ban hành ngày 22/7/2026.
```

Sắp theo cấp hiệu lực từ cao xuống thấp (Luật → Nghị định → Thông tư → địa
phương), trong cùng cấp thì theo thời gian giảm dần. **Chỉ liệt kê văn bản thật
sự được trích dẫn trong thân báo cáo** — danh mục dài hơn phần đã dùng là một
cách tạo cảm giác đầy đặn giả tạo.

Sau danh mục này là hai khối bắt buộc đã nêu ở phần cấu trúc riêng của từng loại
báo cáo: tuyên bố miễn trách nhiệm và hạn chế dữ liệu.
