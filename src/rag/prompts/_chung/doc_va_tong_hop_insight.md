<!-- Dùng chung cho cả ba loại báo cáo.

     Đây là phần định nghĩa lại BẢN CHẤT của báo cáo: không phải mục lục văn
     bản kèm metadata, mà là bản tổng hợp INSIGHT rút ra sau khi đã đọc hết
     từng văn bản. Trước phần này, báo cáo trình bày số hiệu · cơ quan · ngày
     ban hành rồi để người đọc tự mở từng văn bản ra hiểu thêm — đúng thứ phải
     bỏ. -->

## ĐỌC INSIGHT TỪNG VĂN BẢN RỒI MỚI TỔNG HỢP

Hệ thống đã ĐỌC HẾT toàn văn từng văn bản trước khi giao dữ liệu cho bạn, và
đặt kết quả ở khối **`insight_tung_van_ban`**. Mỗi phần tử là một văn bản đã
được chắt lọc, gồm:

| Trường | Nội dung |
|---|---|
| `doc_num`, `title` | định danh — khớp với `danh_sach_van_ban` |
| `mot_cau` | văn bản này làm gì, một câu |
| `pham_vi_dieu_chinh` | điều chỉnh việc gì, ai phải làm theo |
| `noi_dung_chinh` | danh sách luận điểm, mỗi cái gồm `dieu_khoan`, `quy_dinh`, `y_nghia` |
| `nghia_vu_moi` | nghĩa vụ doanh nghiệp phải thực hiện |
| `moc_thoi_gian` | mốc ngày kèm việc |
| `che_tai` | mức phạt nếu có nêu |
| `diem_dang_chu_y` | điểm mới, bất thường, dễ bỏ sót |

**Đây là nguồn CHÍNH để bạn viết nội dung báo cáo.** `danh_sach_van_ban` chỉ là
metadata (số hiệu, cơ quan, ngày, hiệu lực); `chi_tiet_dieu_khoan_chunks` là
trích đoạn thô để đối chiếu câu chữ khi cần. Phần "văn bản này thực chất nói
gì" nằm ở `insight_tung_van_ban`.

**Ba yêu cầu bắt buộc:**

1. **Mọi văn bản trong `danh_sach_van_ban` đều phải được trình bày bằng nội
   dung thực chất**, lấy từ `insight_tung_van_ban` của nó — quy định gì, đặt ra
   nghĩa vụ nào, ngưỡng/mốc/chế tài ra sao. Cấm liệt kê một văn bản chỉ bằng số
   hiệu và ngày rồi bỏ trống phần nội dung. Văn bản nào không có trong
   `insight_tung_van_ban` thì chỉ nhắc ngắn gọn theo thông tin sẵn có (tên, loại,
   ngày, cơ quan) — KHÔNG tự bịa nội dung điều khoản, và KHÔNG giải thích với
   người đọc vì sao thiếu chi tiết (đó là chuyện của hệ thống, không phải của họ).

2. **Giữ nguyên số Điều/Khoản** khi dẫn một luận điểm. `noi_dung_chinh[].dieu_khoan`
   cho sẵn — chép đúng, đó là thứ người đọc dùng để tra ngược bản gốc.

3. **Tổng hợp, không dán.** Không chép nguyên khối `insight_tung_van_ban` vào báo
   cáo. Việc của bạn là gộp insight của nhiều văn bản theo chủ đề, đặt cạnh nhau
   để thấy bức tranh chung, và rút ra điều người đọc cần làm. Một chủ đề thường
   gộp nhiều văn bản; một văn bản có thể góp mặt ở nhiều chủ đề.
