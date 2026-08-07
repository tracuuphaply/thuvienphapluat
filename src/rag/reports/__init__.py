"""Ba loại báo cáo pháp lý và hạ tầng dùng chung của chúng.

  (a) industry.py  — tổng hợp pháp lý của một ngành, trigger theo quý/6 tháng
  (b) new_doc.py   — phân tích văn bản mới ban hành/có hiệu lực, trigger sự kiện A/B/C
  (c) business.py  — chuyên sâu cho doanh nghiệp trong ngành, trigger khi (b) xong

Tách khỏi report_generator.py vì hàm cũ dài 240 dòng làm bốn việc lẫn nhau: dựng
ngữ cảnh, nạp prompt, gọi LLM, sinh báo cáo dự phòng. Nhân bản nó ba lần sẽ làm
xử lý `finish_reason == "length"` trôi khác nhau giữa ba nhánh — và báo cáo bị
cắt giữa chừng mà im lặng thì người đọc tưởng là bản đầy đủ.
"""
