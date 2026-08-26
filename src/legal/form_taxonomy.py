"""
Danh mục phân loại của hai kho biểu mẫu Thư viện Pháp luật.

NGUỒN. Trích trực tiếp từ hai trang tra cứu ngày 18/08/2026:
  - https://thuvienphapluat.vn/bieumau  — 33.820 biểu mẫu
  - https://thuvienphapluat.vn/hopdong  — 662 mẫu hợp đồng

Mã lấy từ `value` của thẻ `<option>` (lĩnh vực) và thuộc tính `atr` của cây lọc
(loại mẫu, nhóm hợp đồng), không phải tự đánh số — đó là mã TVPL dùng trong tham
số URL.

VÌ SAO PHẢI CÓ MODULE RIÊNG, KHÔNG DÙNG LẠI src/legal/tvpl_fields.py. Trang biểu
mẫu dùng danh mục lĩnh vực **47 nhóm**, khác hẳn danh mục **27 nhóm** của trang
tìm văn bản. Trùng tên nhưng khác mã: "Doanh nghiệp" là mã 11 ở đây và mã 1 ở
kia. Trộn hai bộ mã là hỏng dữ liệu ở chỗ khó phát hiện nhất, nên chúng nằm ở hai
module tách bạch và chỉ gặp nhau qua `sang_ma_van_ban()`.

ÁNH XẠ 47 → 27 LÀ SUY ĐOÁN, KHÔNG PHẢI DỮ KIỆN. TVPL không công bố bảng ánh xạ
giữa hai danh mục. Mỗi mục vì vậy mang kèm `nguon`: `chac` khi hai bên gọi cùng
một tên, `suy_dien` khi phải đoán (Xăng dầu → Thương mại). Bên dùng phải đọc được
mức tin cậy đó chứ không nuốt suy đoán như dữ kiện — cùng nguyên tắc với cột
`tvpl_field_source` của bảng documents.

`so_bieu_mau` là số biểu mẫu TVPL công bố ở mỗi nhóm lúc trích. Giữ lại làm mốc
đối chiếu độ phủ, không dùng để tính toán — nó thay đổi mỗi ngày.
"""
from __future__ import annotations

from typing import Literal, TypedDict

# ──────────────────────────────────────────────
# Lĩnh vực của /bieumau — 47 nhóm, mã 1–47
# ──────────────────────────────────────────────


class LinhVucBieuMau(TypedDict):
    ma: int
    ten: str


BIEU_MAU_FIELDS: list[LinhVucBieuMau] = [
    {"ma": 1,  "ten": "An toàn thực phẩm"},
    {"ma": 2,  "ten": "Bảo hiểm"},
    {"ma": 3,  "ten": "Bộ máy hành chính"},
    {"ma": 4,  "ten": "Bổ trợ Tư pháp"},
    {"ma": 5,  "ten": "Bưu chính - Viễn thông"},
    {"ma": 6,  "ten": "Cán bộ - Công chức – Viên chức"},
    {"ma": 7,  "ten": "Công nghệ thông tin"},
    {"ma": 8,  "ten": "Chính sách xã hội"},
    {"ma": 9,  "ten": "Chứng khoán"},
    {"ma": 10, "ten": "Dân sự"},
    {"ma": 11, "ten": "Doanh nghiệp"},
    {"ma": 12, "ten": "Đảng"},
    {"ma": 13, "ten": "Đất đai – Nhà ở"},
    {"ma": 14, "ten": "Đấu thầu"},
    {"ma": 15, "ten": "Đầu tư"},
    {"ma": 16, "ten": "Điện"},
    {"ma": 17, "ten": "Giao thông vận tải"},
    {"ma": 18, "ten": "Giáo dục"},
    {"ma": 19, "ten": "Hoá chất"},
    {"ma": 20, "ten": "Hôn nhân – Gia đình – Thừa kế"},
    {"ma": 21, "ten": "Kế toán – Kiểm toán"},
    {"ma": 22, "ten": "Khiếu nại – Tố cáo"},
    {"ma": 23, "ten": "Khoa học – Công nghệ"},
    {"ma": 24, "ten": "Lao động – Tiền lương"},
    {"ma": 25, "ten": "Lĩnh vực khác"},
    {"ma": 26, "ten": "Nông – Lâm - Ngư nghiệp"},
    {"ma": 27, "ten": "Phòng cháy chữa cháy"},
    {"ma": 28, "ten": "Quốc phòng – An ninh"},
    {"ma": 29, "ten": "Sở hữu trí tuệ"},
    {"ma": 30, "ten": "Tài chính"},
    {"ma": 31, "ten": "Tài nguyên – Môi trường"},
    {"ma": 32, "ten": "Thủ tục tố tụng"},
    {"ma": 33, "ten": "Thủ tục hành chính"},
    {"ma": 34, "ten": "Thi đua - Khen thưởng - Kỷ luật"},
    {"ma": 35, "ten": "Thuế - Phí – Lệ phí"},
    {"ma": 36, "ten": "Thương mại"},
    {"ma": 37, "ten": "Tiền tệ - Ngân hàng"},
    {"ma": 38, "ten": "Trách nhiệm hình sự"},
    {"ma": 39, "ten": "Tư pháp – Hộ tịch"},
    {"ma": 40, "ten": "Văn hoá – Thể thao – Du lịch"},
    {"ma": 41, "ten": "Văn thư - Lưu trữ"},
    {"ma": 42, "ten": "Vi phạm hành chính"},
    {"ma": 43, "ten": "Xăng dầu"},
    {"ma": 44, "ten": "Xây dựng - Đô thị"},
    {"ma": 45, "ten": "Xuất nhập cảnh"},
    {"ma": 46, "ten": "Xuất nhập khẩu"},
    {"ma": 47, "ten": "Y tế"},
]

TEN_LINH_VUC_BM: dict[int, str] = {lv["ma"]: lv["ten"] for lv in BIEU_MAU_FIELDS}

MA_LINH_VUC_KHAC_BM = 25  # "Lĩnh vực khác" — nhóm hứng khi không xếp được


# ──────────────────────────────────────────────
# Loại mẫu của /bieumau — 12 nhóm
# ──────────────────────────────────────────────
# Mã 12 KHÔNG tồn tại: cây lọc nhảy từ 11 (Mẫu tờ trình) sang 13 (Mẫu công văn).
# Đừng "sửa" thành dãy liên tục — mã 12 là mã TVPL đã bỏ, viết lại sẽ lệch URL.

BIEU_MAU_TYPES: dict[int, str] = {
    1:  "Mẫu đơn",
    2:  "Mẫu tờ khai",
    3:  "Mẫu văn bản",
    4:  "Mẫu giấy",
    5:  "Mẫu khác",
    6:  "Mẫu báo cáo",
    7:  "Mẫu quyết định",
    8:  "Mẫu biên bản",
    9:  "Mẫu phiếu",
    10: "Mẫu thông báo",
    11: "Mẫu tờ trình",
    13: "Mẫu công văn",
}


# ──────────────────────────────────────────────
# Nhóm của /hopdong — 22 nhóm, có cây hai tầng
# ──────────────────────────────────────────────


class NhomHopDong(TypedDict):
    ma: int
    ten: str
    cha: int | None
    so_mau_cay: int
    so_mau_rieng: int


# Mã 2 và 8 không tồn tại (nhóm TVPL đã bỏ).
#
# SỐ TRÊN CÂY LỌC LÀ CỘNG DỒN, NHƯNG BỘ LỌC CHỈ TRẢ MẪU CỦA RIÊNG NHÓM. Đo trực
# tiếp ngày 18/08/2026:
#
#     cây ghi "Đất đai, nhà ở (108)"  →  ?type=1  trả về 26
#     cây ghi "Tài sản khác (81)"     →  ?type=19 trả về 26
#     cây ghi "Mua bán nhà đất (22)"  →  ?type=12 trả về 22   (nhóm lá, khớp)
#
# 108 = 26 riêng + 82 của chín nhóm con; 81 = 26 riêng + 55 của ba nhóm con.
# Vì vậy CÀO THEO NHÓM GỐC LÀ THIẾU 137 MẪU, dù phép cộng số trên cây ra đúng
# 662 và trông rất thuyết phục. Phải đi hết cả 22 nhóm:
#
#     26+82 + 94+32+14+29+36+22 + 26+55 + 39+207 = 662
#
# Không trùng lặp, vì mẫu của nhóm con KHÔNG xuất hiện lại ở nhóm cha.
HOP_DONG_CATEGORIES: list[NhomHopDong] = [
    {"ma": 1,  "ten": "Đất đai, nhà ở",             "cha": None, "so_mau_cay": 108, "so_mau_rieng": 26},
    {"ma": 9,  "ten": "Bảo lãnh nhà đất",           "cha": 1,    "so_mau_cay": 3,   "so_mau_rieng": 3},
    {"ma": 10, "ten": "Chuyển đổi nhà đất",         "cha": 1,    "so_mau_cay": 4,   "so_mau_rieng": 4},
    {"ma": 11, "ten": "Môi giới nhà đất",           "cha": 1,    "so_mau_cay": 1,   "so_mau_rieng": 1},
    {"ma": 12, "ten": "Mua bán nhà đất",            "cha": 1,    "so_mau_cay": 22,  "so_mau_rieng": 22},
    {"ma": 13, "ten": "Mượn nhà đất",               "cha": 1,    "so_mau_cay": 2,   "so_mau_rieng": 2},
    {"ma": 14, "ten": "Tặng - cho nhà đất",         "cha": 1,    "so_mau_cay": 4,   "so_mau_rieng": 4},
    {"ma": 15, "ten": "Thế chấp nhà đất",           "cha": 1,    "so_mau_cay": 14,  "so_mau_rieng": 14},
    {"ma": 16, "ten": "Thuê mướn nhà đất",          "cha": 1,    "so_mau_cay": 25,  "so_mau_rieng": 25},
    {"ma": 17, "ten": "Ủy quyền nhà đất",           "cha": 1,    "so_mau_cay": 7,   "so_mau_rieng": 7},
    {"ma": 3,  "ten": "Dịch vụ",                    "cha": None, "so_mau_cay": 94,  "so_mau_rieng": 94},
    {"ma": 4,  "ten": "Kinh doanh-hợp tác",         "cha": None, "so_mau_cay": 32,  "so_mau_rieng": 32},
    {"ma": 5,  "ten": "Sở hữu trí tuệ",             "cha": None, "so_mau_cay": 14,  "so_mau_rieng": 14},
    {"ma": 6,  "ten": "Lao động",                   "cha": None, "so_mau_cay": 29,  "so_mau_rieng": 29},
    {"ma": 7,  "ten": "Xây dựng",                   "cha": None, "so_mau_cay": 36,  "so_mau_rieng": 36},
    {"ma": 18, "ten": "Hàng hóa",                   "cha": None, "so_mau_cay": 22,  "so_mau_rieng": 22},
    {"ma": 19, "ten": "Tài sản khác",               "cha": None, "so_mau_cay": 81,  "so_mau_rieng": 26},
    {"ma": 21, "ten": "Vật",                        "cha": 19,   "so_mau_cay": 14,  "so_mau_rieng": 14},
    {"ma": 22, "ten": "Tiền",                       "cha": 19,   "so_mau_cay": 33,  "so_mau_rieng": 33},
    {"ma": 23, "ten": "Giấy tờ có giá",             "cha": 19,   "so_mau_cay": 8,   "so_mau_rieng": 8},
    {"ma": 20, "ten": "Biên bản thanh lý, phụ lục", "cha": None, "so_mau_cay": 39,  "so_mau_rieng": 39},
    {"ma": 24, "ten": "Khác",                       "cha": None, "so_mau_cay": 207, "so_mau_rieng": 207},
]

TEN_NHOM_HD: dict[int, str] = {n["ma"]: n["ten"] for n in HOP_DONG_CATEGORIES}

#: Bộ mã phải cào để phủ trọn kho — CẢ 22 nhóm, không phải 10 nhóm gốc.
#: Nhóm con đứng trước nhóm cha trong thứ tự này để mẫu nhận nhãn cụ thể nhất.
HOP_DONG_CRAWL_CODES: tuple[int, ...] = tuple(
    sorted((n["ma"] for n in HOP_DONG_CATEGORIES),
           key=lambda ma: (next(x["cha"] for x in HOP_DONG_CATEGORIES
                                if x["ma"] == ma) is None, ma))
)

#: Nhóm gốc — chỉ dùng để dựng mục lục hai tầng, KHÔNG dùng để cào.
HOP_DONG_ROOT_CODES: tuple[int, ...] = tuple(
    n["ma"] for n in HOP_DONG_CATEGORIES if n["cha"] is None
)

TONG_MAU_HOP_DONG = 662


# ──────────────────────────────────────────────
# Ánh xạ 47 lĩnh vực biểu mẫu → 27 lĩnh vực văn bản
# ──────────────────────────────────────────────

DoTinCay = Literal["chac", "suy_dien"]

#: (mã lĩnh vực biểu mẫu) → (mã lĩnh vực văn bản 1–27, mức tin cậy).
#: `chac` = hai danh mục gọi cùng một tên. `suy_dien` = phải đoán, có thể sai.
_ANH_XA: dict[int, tuple[int, DoTinCay]] = {
    1:  (24, "suy_dien"),  # An toàn thực phẩm    → Thể thao - Y tế
    2:  (8,  "chac"),      # Bảo hiểm
    3:  (15, "chac"),      # Bộ máy hành chính
    4:  (13, "suy_dien"),  # Bổ trợ Tư pháp       → Dịch vụ pháp lý
    5:  (11, "suy_dien"),  # Bưu chính - Viễn thông → Công nghệ thông tin
    6:  (15, "suy_dien"),  # Cán bộ - CC - VC     → Bộ máy hành chính
    7:  (11, "chac"),      # Công nghệ thông tin
    8:  (26, "suy_dien"),  # Chính sách xã hội    → Văn hóa - Xã hội
    9:  (7,  "chac"),      # Chứng khoán
    10: (25, "suy_dien"),  # Dân sự               → Quyền dân sự
    11: (1,  "chac"),      # Doanh nghiệp
    12: (15, "suy_dien"),  # Đảng                 → Bộ máy hành chính
    13: (12, "suy_dien"),  # Đất đai – Nhà ở      → Bất động sản
    14: (2,  "suy_dien"),  # Đấu thầu             → Đầu tư
    15: (2,  "chac"),      # Đầu tư
    16: (3,  "suy_dien"),  # Điện                 → Thương mại
    17: (21, "chac"),      # Giao thông vận tải   → Giao thông - Vận tải
    18: (22, "chac"),      # Giáo dục
    19: (3,  "suy_dien"),  # Hoá chất             → Thương mại
    20: (25, "suy_dien"),  # Hôn nhân – GĐ – TK   → Quyền dân sự
    21: (9,  "chac"),      # Kế toán – Kiểm toán
    22: (18, "suy_dien"),  # Khiếu nại – Tố cáo   → Thủ tục Tố tụng
    23: (11, "suy_dien"),  # Khoa học – Công nghệ → Công nghệ thông tin
    24: (10, "chac"),      # Lao động – Tiền lương
    25: (27, "chac"),      # Lĩnh vực khác
    26: (23, "suy_dien"),  # Nông – Lâm - Ngư     → Tài nguyên - Môi trường
    27: (20, "suy_dien"),  # Phòng cháy chữa cháy → Xây dựng - Đô thị
    28: (15, "suy_dien"),  # Quốc phòng – An ninh → Bộ máy hành chính
    29: (14, "chac"),      # Sở hữu trí tuệ
    30: (19, "suy_dien"),  # Tài chính            → Tài chính nhà nước
    31: (23, "chac"),      # Tài nguyên – Môi trường
    32: (18, "chac"),      # Thủ tục tố tụng
    33: (15, "suy_dien"),  # Thủ tục hành chính   → Bộ máy hành chính
    34: (15, "suy_dien"),  # Thi đua - KT - KL    → Bộ máy hành chính
    35: (6,  "chac"),      # Thuế - Phí – Lệ phí
    36: (3,  "chac"),      # Thương mại
    37: (5,  "chac"),      # Tiền tệ - Ngân hàng
    38: (17, "chac"),      # Trách nhiệm hình sự
    39: (13, "suy_dien"),  # Tư pháp – Hộ tịch    → Dịch vụ pháp lý
    40: (26, "suy_dien"),  # Văn hoá – TT – DL    → Văn hóa - Xã hội
    41: (15, "suy_dien"),  # Văn thư - Lưu trữ    → Bộ máy hành chính
    42: (16, "chac"),      # Vi phạm hành chính
    43: (3,  "suy_dien"),  # Xăng dầu             → Thương mại
    44: (20, "chac"),      # Xây dựng - Đô thị
    45: (15, "suy_dien"),  # Xuất nhập cảnh       → Bộ máy hành chính
    46: (4,  "chac"),      # Xuất nhập khẩu
    47: (24, "chac"),      # Y tế                 → Thể thao - Y tế
}

#: Mã "Lĩnh vực khác" của danh mục VĂN BẢN (27 nhóm) — xem src/legal/tvpl_fields.py.
_MA_KHAC_VAN_BAN = 27


# ──────────────────────────────────────────────
# Nhóm nghiệp vụ doanh nghiệp — tập ĐÓNG 12 nhóm
# ──────────────────────────────────────────────
# Đây là trục người dùng thật sự tra cứu: không ai hỏi "biểu mẫu lĩnh vực 21",
# người ta hỏi "mẫu nào để đăng ký thay đổi người đại diện". Tập phải ĐÓNG vì
# nó là mục lục trang công khai và menu của lệnh Telegram — biên trôi thì mục
# lục vỡ, đúng lý do src/legal/tvpl_fields.py chọn danh mục đóng 27 nhóm.

NGHIEP_VU: dict[str, str] = {
    "dkkd":             "Thành lập & thay đổi đăng ký doanh nghiệp",
    "lao_dong_bhxh":    "Lao động, tiền lương, bảo hiểm xã hội",
    "thue_hoa_don":     "Thuế, hoá đơn, phí và lệ phí",
    "ke_toan":          "Kế toán, kiểm toán, báo cáo tài chính",
    "xnk_hai_quan":     "Xuất nhập khẩu, hải quan",
    "dau_tu":           "Đầu tư, dự án, đấu thầu",
    "dat_dai_xay_dung": "Đất đai, mặt bằng, xây dựng",
    "shtt":             "Sở hữu trí tuệ, nhãn hiệu",
    "pccc_moi_truong":  "Phòng cháy, môi trường, an toàn thực phẩm",
    "giay_phep_nganh":  "Giấy phép con theo ngành nghề",
    "hop_dong":         "Hợp đồng và giao dịch",
    "khac":             "Nghiệp vụ khác",
}

MA_NGHIEP_VU_KHAC = "khac"


# ──────────────────────────────────────────────
# Nhóm sự kiện đời người — trục của CÁ NHÂN
# ──────────────────────────────────────────────
# Trục KHÁC HẲN nhóm nghiệp vụ doanh nghiệp, không phải bản dịch của nó.
# Doanh nghiệp tra theo NGHIỆP VỤ ĐỊNH KỲ: đến kỳ thì khai thuế, đến hạn thì nộp
# báo cáo tài chính — việc lặp lại, biết trước, gắn với bộ máy.
# Cá nhân tra theo SỰ KIỆN xảy ra với mình: sinh con, kết hôn, mua nhà, mất
# việc, bị phạt, người thân qua đời — việc đến bất ngờ, thường chỉ gặp một vài
# lần trong đời, và lúc gặp thì không biết bắt đầu từ đâu.
#
# Ép cá nhân vào 12 nhóm nghiệp vụ doanh nghiệp là bắt người vừa mất việc đi tìm
# mục "Lao động, tiền lương, bảo hiểm xã hội" — đúng chữ mà sai hoàn toàn cách
# họ nghĩ về việc đang xảy ra với mình.
#
# Tập ĐÓNG, cùng lý do với 12 nhóm doanh nghiệp: nó là mục lục trang công khai,
# biên trôi thì mục lục vỡ.

NGHIEP_VU_CA_NHAN: dict[str, str] = {
    "ho_tich":            "Hộ tịch, giấy tờ tuỳ thân, cư trú",
    "hon_nhan_gia_dinh":  "Kết hôn, ly hôn, con cái, cấp dưỡng",
    "thua_ke_di_chuc":    "Di chúc, thừa kế, tặng cho tài sản",
    "nha_dat_ca_nhan":    "Nhà ở, đất đai, sổ đỏ của cá nhân",
    "lao_dong_nguoi_lam": "Việc làm, hợp đồng, nghỉ việc — phía người lao động",
    "bhxh_bhyt_huu_tri":  "Bảo hiểm xã hội, y tế, thai sản, thất nghiệp, hưu trí",
    "thue_tncn":          "Thuế thu nhập cá nhân, giảm trừ gia cảnh",
    "vay_no_giao_dich":   "Vay mượn, đặt cọc, uỷ quyền, bồi thường dân sự",
    "khieu_nai_to_tung":  "Khiếu nại, tố cáo, khởi kiện, thi hành án",
    "vi_pham_hanh_chinh": "Xử phạt hành chính, khiếu nại quyết định phạt",
    "giao_duc_hoc_tap":   "Nhập học, học phí, học bổng, vay vốn sinh viên",
    "y_te_kham_benh":     "Khám chữa bệnh, giám định y khoa, hồ sơ bệnh án",
    "chinh_sach_xa_hoi":  "Hộ nghèo, người có công, khuyết tật, người cao tuổi",
    "xuat_nhap_canh":     "Hộ chiếu, thị thực, tạm trú, tạm vắng",
    "khac_ca_nhan":       "Việc cá nhân khác",
}

MA_NGHIEP_VU_CA_NHAN_KHAC = "khac_ca_nhan"


# ──────────────────────────────────────────────
# Đối tượng điền biểu mẫu
# ──────────────────────────────────────────────
# Trục quyết định của phễu lọc. Lĩnh vực KHÔNG phân biệt được: "Kế toán – Kiểm
# toán" chứa cả biểu quyết toán ngân sách của Kho bạc Nhà nước lẫn báo cáo tài
# chính doanh nghiệp. Thứ phân biệt là AI cầm bút điền.

DOANH_NGHIEP = "doanh_nghiep"
CO_QUAN_NHA_NUOC = "co_quan_nha_nuoc"
CA_NHAN = "ca_nhan"
KHAC = "khac"

DOI_TUONG_DIEN: dict[str, str] = {
    DOANH_NGHIEP:     "Doanh nghiệp, hộ kinh doanh, hợp tác xã",
    CO_QUAN_NHA_NUOC: "Cơ quan nhà nước, đơn vị sự nghiệp công",
    CA_NHAN:          "Cá nhân, không nhân danh hoạt động kinh doanh",
    KHAC:             "Chưa xác định được",
}


# ──────────────────────────────────────────────
# Truy vấn
# ──────────────────────────────────────────────


def ten_linh_vuc_bieu_mau(ma: int | None) -> str:
    """Mã lĩnh vực biểu mẫu → tên. Mã lạ hoặc rỗng rơi về "Lĩnh vực khác"."""
    return TEN_LINH_VUC_BM.get(ma or 0, TEN_LINH_VUC_BM[MA_LINH_VUC_KHAC_BM])


def ten_loai_mau(ma: int | None) -> str:
    """Mã loại mẫu → tên. Mã lạ rơi về "Mẫu khác"."""
    return BIEU_MAU_TYPES.get(ma or 0, BIEU_MAU_TYPES[5])


def ten_nhom_hop_dong(ma: int | None) -> str:
    """Mã nhóm hợp đồng → tên. Mã lạ rơi về "Khác"."""
    return TEN_NHOM_HD.get(ma or 0, TEN_NHOM_HD[24])


def sang_ma_van_ban(ma_bieu_mau: int | None) -> tuple[int, DoTinCay]:
    """Mã lĩnh vực biểu mẫu (1–47) → mã lĩnh vực văn bản (1–27) kèm mức tin cậy.

    Trả kèm `chac` / `suy_dien` chứ không trả mỗi con số: bên gọi phải phân biệt
    được đâu là dữ kiện đâu là phỏng đoán. Mã không có trong bảng rơi về "Lĩnh
    vực khác" và luôn mang nhãn `suy_dien`.
    """
    return _ANH_XA.get(ma_bieu_mau or 0, (_MA_KHAC_VAN_BAN, "suy_dien"))


def la_nghiep_vu_hop_le(ma: str, ca_nhan: bool = False) -> bool:
    return ma in (NGHIEP_VU_CA_NHAN if ca_nhan else NGHIEP_VU)


def chuan_hoa_nghiep_vu(ma_list, ca_nhan: bool = False) -> list[str]:
    """Giữ lại các mã nghiệp vụ hợp lệ, khử trùng, giữ nguyên thứ tự.

    Danh sách rỗng sau khi lọc trả về nhóm "khác" chứ không trả rỗng: biểu mẫu
    không nhóm được vẫn phải tra được, để trong hư vô là mất luôn.

    `ca_nhan=True` chấm theo tập 15 nhóm sự kiện đời người thay vì 12 nhóm nghiệp
    vụ doanh nghiệp. MỘT hàm cho cả hai tập, không phải hai hàm: bài học "rỗng thì
    trả nhóm khác" ở trên phải đúng cho cả hai, mà nhân đôi hàm là nhân đôi chỗ
    để quên nó.
    """
    hop_le = NGHIEP_VU_CA_NHAN if ca_nhan else NGHIEP_VU
    mac_dinh = MA_NGHIEP_VU_CA_NHAN_KHAC if ca_nhan else MA_NGHIEP_VU_KHAC
    out: list[str] = []
    for ma in ma_list or ():
        key = str(ma).strip().lower()
        if key in hop_le and key not in out:
            out.append(key)
    return out or [mac_dinh]


__all__ = [
    "BIEU_MAU_FIELDS", "TEN_LINH_VUC_BM", "MA_LINH_VUC_KHAC_BM",
    "BIEU_MAU_TYPES",
    "HOP_DONG_CATEGORIES", "TEN_NHOM_HD", "HOP_DONG_CRAWL_CODES",
    "HOP_DONG_ROOT_CODES",
    "TONG_MAU_HOP_DONG",
    "NGHIEP_VU", "MA_NGHIEP_VU_KHAC",
    "NGHIEP_VU_CA_NHAN", "MA_NGHIEP_VU_CA_NHAN_KHAC",
    "DOI_TUONG_DIEN", "DOANH_NGHIEP", "CO_QUAN_NHA_NUOC", "CA_NHAN", "KHAC",
    "ten_linh_vuc_bieu_mau", "ten_loai_mau", "ten_nhom_hop_dong",
    "sang_ma_van_ban", "la_nghiep_vu_hop_le", "chuan_hoa_nghiep_vu",
]
