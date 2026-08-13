# Hướng dẫn sử dụng Bot Telegram

Bot Telegram là bảng điều khiển để **đặt, chạy và nhận báo cáo pháp lý** (dạng
PDF), cùng vài lệnh tra cứu nhanh. Bot chỉ *xếp hàng và điều khiển* — việc sinh
báo cáo do worker chạy, và file PDF được gửi lại qua chính bot.

---

## 1. Truy cập

- Bot hiện tại: **`@gatlas_legal_bot`**.
- Bot **chỉ nhận lệnh từ chat được cấu hình** (biến `TELEGRAM_CHAT_ID` /
  `TELEGRAM_ADMIN_CHAT_ID` trong `.env`). Chat khác gõ lệnh sẽ bị từ chối.
- Lệnh `/sync` chỉ dành cho **admin** (`TELEGRAM_ADMIN_CHAT_ID`).

## 2. Khởi động bot (dành cho người vận hành)

Bot là một tiến trình chạy nền, phải bật thì Telegram mới nhận lệnh:

```bash
python -m src.notification.telegram_bot_server
```

Giữ tiến trình này sống. Muốn tự khởi động theo máy thì cài qua
`scripts/install_scheduler.sh` (hoặc launchd/systemd tuỳ máy).

Điều kiện để báo cáo chạy được: `.env` đã có `OPENAI_API_BASE`, khoá API,
`REPORT_MODEL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

---

## 3. Bảng lệnh

| Lệnh | Việc | Ghi chú |
|---|---|---|
| `/help` (hoặc `/start`) | Hiện menu và danh sách lệnh | |
| `/baocao` | Hướng dẫn báo cáo + tóm tắt hàng đợi | |
| `/baocao a <mã ngành>` | Đặt **báo cáo tổng hợp ngành** | vd `/baocao a K` |
| `/baocao b` | Đặt **báo cáo cập nhật văn bản mới** | Tự lọc "liên quan doanh nghiệp" |
| `/nganh` | Danh sách 21 mã ngành VSIC | |
| `/hangdoi` | Xem báo cáo đang chờ / đang chạy / vừa xong | |
| `/chay` | **Chạy hàng đợi ngay**, không đợi lịch | Chỉ báo thống kê, KHÔNG tự gửi PDF |
| `/xem <id>` | Chi tiết một báo cáo + **gửi file PDF** | vd `/xem 35` |
| `/huy <id>` | Huỷ một báo cáo còn đang chờ | Không huỷ được cái đã chạy |
| `/search <từ khóa>` | Tìm văn bản (vector + BM25) | Gõ thẳng câu hỏi cũng được, khỏi `/search` |
| `/impact <số hiệu>` | Quan hệ dẫn chiếu của một văn bản | vd `/impact 108/2026/TT-BTC` |
| `/sync` | Đồng bộ vault Obsidian + RAG | **Chỉ admin** |

> Có thể **gõ thẳng câu hỏi** vào ô chat (không cần `/search`) — bot tự tìm.

---

## 4. Luồng tạo & nhận một báo cáo (quan trọng nhất)

Bốn bước:

```
1) /baocao b          → bot trả về "Đã xếp hàng báo cáo #<id>"
2) /chay              → sinh báo cáo + dựng PDF (đợi vài phút)
3) /hangdoi           → thấy trạng thái DONE
4) /xem <id>          → nhận file PDF ngay trong Telegram
```

Với báo cáo ngành thì đổi bước 1 thành `/baocao a <mã ngành>` (vd `/baocao a K`).

**Vì sao có bước `/xem`:** `/chay` chỉ *chạy* hàng đợi và báo thống kê
(bao nhiêu cái xong/lỗi/bị chặn). File PDF **không tự gửi** — phải `/xem <id>`
để bot đính kèm file. Xem `/hangdoi` để biết id.

---

## 5. Ba loại báo cáo

| Loại | Lệnh đặt | Nội dung |
|---|---|---|
| **(a)** Tổng hợp ngành | `/baocao a <mã>` | Toàn cảnh khung pháp lý một ngành VSIC |
| **(b)** Cập nhật văn bản mới | `/baocao b` | Văn bản mới/đổi hiệu lực: cái gì đổi, ai phải làm gì, từ ngày nào |
| **(c)** Chuyên sâu doanh nghiệp | *(không đặt tay)* | Sinh **tự động** sau khi (b) xong, cho từng ngành bị ảnh hưởng mạnh |

Báo cáo **(c) không đặt trực tiếp được** — nó chỉ ra đời khi một báo cáo (b) tạo
được ngành chịu tác động vượt ngưỡng. Muốn có (c): chạy (b) trước, để hệ thống
tự chuỗi.

Mọi báo cáo hướng tới **chủ doanh nghiệp**: chỉ nhận văn bản thuộc lĩnh vực kinh
doanh và cấp trung ương (bỏ y tế/giáo dục/văn hoá và văn bản cấp tỉnh). Chỉnh bộ
lọc qua `BUSINESS_FIELD_CODES` và `REPORT_CENTRAL_ONLY` trong `.env`.

---

## 6. Những điều cần biết

- **PDF chỉ đến qua `/xem <id>`** — không tự đẩy sau `/chay`.
- **Trần mỗi ngày:** hệ thống chỉ chạy `MAX_REPORTS_PER_DAY` (mặc định 5) báo cáo/ngày;
  cái vượt trần bị dời sang hôm sau (đây là cơ chế chống ngập, không phải lỗi).
- **`DONE` mới có PDF. `BLOCKED_CITATION`** = báo cáo bị chặn vì có số hiệu văn
  bản không kiểm chứng được (mô hình viết sai hoặc bịa) → **không xuất PDF**,
  chỉ giữ bản markdown để soi. Càng nhiều văn bản trong một báo cáo, xác suất bị
  chặn càng cao; nên chốt (b) theo lô nhỏ.
- **Mỗi báo cáo xuất 2 bản PDF:** `_khach` (gửi doanh nghiệp) và `_doitac` (có
  lời ngỏ hợp tác, gửi công ty luật). `/xem` gửi bản khách trước.
- **Không tạo báo cáo trùng trong ngày:** gõ `/baocao a K` hai lần cùng ngày chỉ
  ra một báo cáo (bot báo "đã có trong hàng đợi").
- **`#id` chỉ là số thứ tự** job trong hệ thống, không mang ý nghĩa nội dung;
  ngành/số hiệu thật in trên bìa PDF.

---

## 7. Xử lý sự cố

| Hiện tượng | Nguyên nhân & cách xử lý |
|---|---|
| Bot không phản hồi | Tiến trình bot chưa chạy (mục 2), hoặc bạn gõ từ chat không được cấp quyền |
| `/baocao b` báo "không có văn bản mới" | Kỳ này không có văn bản **liên quan doanh nghiệp + cấp trung ương** nào chưa được báo cáo. Thử `/baocao a <mã ngành>` |
| `/chay` xong nhưng không nhận PDF | Đúng thiết kế — dùng `/xem <id>` để lấy file; `/hangdoi` để biết id |
| `/xem` báo "xong nhưng không có PDF" | Thường do thiếu font khi dựng PDF, hoặc báo cáo bị `BLOCKED_CITATION`. Xem log máy chủ |
| Báo cáo `BLOCKED_CITATION` | Có số hiệu không kiểm chứng được. Bản markdown vẫn lưu ở `data/reports/…` để soi mô hình viết sai gì |
| Báo cáo mãi ở `QUEUED` | Chưa `/chay`, hoặc bị dời sang hôm sau do chạm trần ngày. `/hangdoi` xem lịch |

Muốn chạy/kiểm tra ngoài Telegram (không gửi file, chỉ dựng ra đĩa):

```bash
python -m scripts.run_report_worker --status
```

---

*Báo cáo giữ đúng vai trò tài liệu pháp lý tham khảo, không thay thế tư vấn pháp
lý chính thức.*
