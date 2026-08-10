"""
Danh mục lĩnh vực của Thư viện Pháp luật — 27 nhóm, mã 1–27.

NGUỒN. Trích từ bộ lọc "Lĩnh vực" tại https://thuvienphapluat.vn/page/tim-van-ban.aspx
ngày 10/08/2026. Mã lấy từ thuộc tính `atr` của thẻ lọc, không phải tự đánh số —
đó là mã TVPL dùng trong URL và tham số `fields=` của trang tìm kiếm.

VÌ SAO DÙNG DANH MỤC NÀY THAY VÌ CỦA BỘ TƯ PHÁP. `field_name` mà gateway Bộ Tư
pháp trả về là văn bản tự do, không phải danh mục có kiểm soát: 4.466 văn bản
trong kho rơi vào 203 giá trị khác nhau, trong đó 75 giá trị chỉ có đúng MỘT văn
bản. Cây thư mục dựng trên đó có 203 nhánh gốc, phần lớn chứa một file.

Danh mục TVPL là tập ĐÓNG 27 nhóm nên cây thư mục có biên cố định, và nó cũng là
phân loại người dùng Việt Nam quen tra cứu.

`so_van_ban_tvpl` là số văn bản TVPL công bố ở mỗi lĩnh vực lúc trích. Giữ lại
làm mốc đối chiếu độ phủ, không dùng để tính toán — nó thay đổi mỗi ngày.
"""
from __future__ import annotations

from typing import TypedDict


class LinhVuc(TypedDict):
    ma: int
    ten: str
    so_van_ban_tvpl: int


TVPL_FIELDS: list[LinhVuc] = [
    {"ma": 1,  "ten": "Doanh nghiệp",            "so_van_ban_tvpl": 14634},
    {"ma": 2,  "ten": "Đầu tư",                  "so_van_ban_tvpl": 16192},
    {"ma": 3,  "ten": "Thương mại",              "so_van_ban_tvpl": 26782},
    {"ma": 4,  "ten": "Xuất nhập khẩu",          "so_van_ban_tvpl": 12749},
    {"ma": 5,  "ten": "Tiền tệ - Ngân hàng",     "so_van_ban_tvpl": 5869},
    {"ma": 6,  "ten": "Thuế - Phí - Lệ Phí",     "so_van_ban_tvpl": 19100},
    {"ma": 7,  "ten": "Chứng khoán",             "so_van_ban_tvpl": 947},
    {"ma": 8,  "ten": "Bảo hiểm",                "so_van_ban_tvpl": 3397},
    {"ma": 9,  "ten": "Kế toán - Kiểm toán",     "so_van_ban_tvpl": 1990},
    {"ma": 10, "ten": "Lao động - Tiền lương",   "so_van_ban_tvpl": 18201},
    {"ma": 11, "ten": "Công nghệ thông tin",     "so_van_ban_tvpl": 17013},
    {"ma": 12, "ten": "Bất động sản",            "so_van_ban_tvpl": 29201},
    {"ma": 13, "ten": "Dịch vụ pháp lý",         "so_van_ban_tvpl": 4083},
    {"ma": 14, "ten": "Sở hữu trí tuệ",          "so_van_ban_tvpl": 1342},
    {"ma": 15, "ten": "Bộ máy hành chính",       "so_van_ban_tvpl": 159040},
    {"ma": 16, "ten": "Vi phạm hành chính",      "so_van_ban_tvpl": 2551},
    {"ma": 17, "ten": "Trách nhiệm hình sự",     "so_van_ban_tvpl": 1768},
    {"ma": 18, "ten": "Thủ tục Tố tụng",         "so_van_ban_tvpl": 2726},
    {"ma": 19, "ten": "Tài chính nhà nước",      "so_van_ban_tvpl": 53061},
    {"ma": 20, "ten": "Xây dựng - Đô thị",       "so_van_ban_tvpl": 28021},
    {"ma": 21, "ten": "Giao thông - Vận tải",    "so_van_ban_tvpl": 19256},
    {"ma": 22, "ten": "Giáo dục",                "so_van_ban_tvpl": 21663},
    {"ma": 23, "ten": "Tài nguyên - Môi trường", "so_van_ban_tvpl": 33461},
    {"ma": 24, "ten": "Thể thao - Y tế",         "so_van_ban_tvpl": 25954},
    {"ma": 25, "ten": "Quyền dân sự",            "so_van_ban_tvpl": 7547},
    {"ma": 26, "ten": "Văn hóa - Xã hội",        "so_van_ban_tvpl": 49127},
    {"ma": 27, "ten": "Lĩnh vực khác",           "so_van_ban_tvpl": 10677},
]

TEN_THEO_MA: dict[int, str] = {lv["ma"]: lv["ten"] for lv in TVPL_FIELDS}
MA_THEO_TEN: dict[str, int] = {lv["ten"]: lv["ma"] for lv in TVPL_FIELDS}

# Nhóm hứng văn bản chưa xếp được. Dùng đúng nhãn của TVPL chứ không tự đặt
# "Chưa phân loại": người mở thư mục sẽ tìm nó trên trang TVPL và thấy đúng chỗ.
MA_KHAC = 27
TEN_KHAC = TEN_THEO_MA[MA_KHAC]


def ten_linh_vuc(ma: int | None) -> str:
    """Mã → tên. Mã lạ hoặc rỗng đều rơi về "Lĩnh vực khác"."""
    return TEN_THEO_MA.get(ma or 0, TEN_KHAC)


def thu_muc(ma: int | None) -> str:
    """Tên thư mục cấp 1 trên Drive: có mã ở đầu để sắp xếp ổn định.

    Không dùng tên trần: Drive sắp theo bảng chữ cái, nên "Bất động sản" nằm
    trước "Doanh nghiệp" và thứ tự đổi mỗi khi TVPL đổi tên một nhóm. Có mã thì
    thứ tự cố định và khớp với thứ tự trên chính trang TVPL.
    """
    ma = ma if ma in TEN_THEO_MA else MA_KHAC
    return f"{ma:02d}. {TEN_THEO_MA[ma]}"
