"""
Hệ thống ngành kinh tế Việt Nam (VSIC) — cấp 1.

Ban hành kèm Quyết định 27/2018/QĐ-TTg ngày 06/7/2018 của Thủ tướng Chính phủ.
Chỉ lấy 21 đầu mục cấp 1 (ký hiệu bằng chữ cái A–U); tên ngành trích trực tiếp
từ Phụ lục I của quyết định.

Bộ phân loại 10 ngành tự đặt trước đây được thay bằng danh mục này để báo cáo
nói cùng ngôn ngữ với đăng ký kinh doanh của doanh nghiệp — mã ngành trên giấy
phép của họ chính là mã ở đây.

`tu_khoa` là thuật ngữ dùng để dò văn bản quy phạm pháp luật thuộc ngành, không
phải tên hoạt động kinh tế: văn bản luật viết "kinh doanh bất động sản", "nhà ở
thương mại" chứ không viết "hoạt động kinh doanh bất động sản" theo đúng tên
ngành VSIC.
"""
from __future__ import annotations

from typing import TypedDict


class Nganh(TypedDict):
    ma: str
    ten: str
    ten_ngan: str
    tu_khoa: list[str]


VSIC_LEVEL1: list[Nganh] = [
    {
        "ma": "A",
        "ten": "NÔNG NGHIỆP, LÂM NGHIỆP VÀ THUỶ SẢN",
        "ten_ngan": "Nông nghiệp, lâm nghiệp và thuỷ sản",
        "tu_khoa": ["nông nghiệp", "lâm nghiệp", "thủy sản", "thuỷ sản", "trồng trọt",
                    "chăn nuôi", "thú y", "giống cây trồng", "phân bón", "thuốc bảo vệ thực vật",
                    "khai thác thủy sản", "nuôi trồng thủy sản", "nông thôn", "đất nông nghiệp"],
    },
    {
        "ma": "B",
        "ten": "KHAI KHOÁNG",
        "ten_ngan": "Khai khoáng",
        "tu_khoa": ["khai khoáng", "khoáng sản", "khai thác than", "dầu thô", "khí đốt tự nhiên",
                    "quặng", "mỏ", "giấy phép khai thác", "thăm dò khoáng sản"],
    },
    {
        "ma": "C",
        "ten": "CÔNG NGHIỆP CHẾ BIẾN, CHẾ TẠO",
        "ten_ngan": "Công nghiệp chế biến, chế tạo",
        "tu_khoa": ["chế biến", "chế tạo", "sản xuất công nghiệp", "nhà máy", "gia công",
                    "an toàn thực phẩm", "sản xuất thực phẩm", "dệt may", "da giày",
                    "hóa chất", "cơ khí", "điện tử", "vật liệu xây dựng"],
    },
    {
        "ma": "D",
        "ten": "SẢN XUẤT VÀ PHÂN PHỐI ĐIỆN, KHÍ ĐỐT, NƯỚC NÓNG, HƠI NƯỚC VÀ ĐIỀU HOÀ KHÔNG KHÍ",
        "ten_ngan": "Sản xuất và phân phối điện, khí đốt",
        "tu_khoa": ["điện lực", "phát điện", "truyền tải điện", "phân phối điện", "giá điện",
                    "năng lượng tái tạo", "điện mặt trời", "điện gió", "khí đốt", "hơi nước"],
    },
    {
        "ma": "E",
        "ten": "CUNG CẤP NƯỚC; HOẠT ĐỘNG QUẢN LÝ VÀ XỬ LÝ RÁC THẢI, NƯỚC THẢI",
        "ten_ngan": "Cung cấp nước; xử lý rác thải, nước thải",
        "tu_khoa": ["cấp nước", "nước sạch", "nước thải", "rác thải", "chất thải rắn",
                    "chất thải nguy hại", "xử lý chất thải", "tái chế", "bảo vệ môi trường",
                    "giấy phép môi trường"],
    },
    {
        "ma": "F",
        "ten": "XÂY DỰNG",
        "ten_ngan": "Xây dựng",
        "tu_khoa": ["xây dựng", "công trình xây dựng", "nhà thầu", "giấy phép xây dựng",
                    "dự toán xây dựng", "quy hoạch xây dựng", "nghiệm thu công trình",
                    "an toàn lao động xây dựng", "đấu thầu xây lắp"],
    },
    {
        "ma": "G",
        "ten": "BÁN BUÔN VÀ BÁN LẺ; SỬA CHỮA Ô TÔ, MÔ TÔ, XE MÁY VÀ XE CÓ ĐỘNG CƠ KHÁC",
        "ten_ngan": "Bán buôn, bán lẻ; sửa chữa ô tô, xe máy",
        "tu_khoa": ["bán buôn", "bán lẻ", "thương mại", "phân phối hàng hóa", "siêu thị",
                    "xuất nhập khẩu", "thương mại điện tử", "khuyến mại", "bảo vệ quyền lợi người tiêu dùng",
                    "sửa chữa ô tô", "kinh doanh xăng dầu"],
    },
    {
        "ma": "H",
        "ten": "VẬN TẢI KHO BÃI",
        "ten_ngan": "Vận tải kho bãi",
        "tu_khoa": ["vận tải", "đường bộ", "đường sắt", "đường thủy", "hàng hải", "hàng không",
                    "kho bãi", "logistics", "giao thông", "phương tiện vận tải", "cảng biển"],
    },
    {
        "ma": "I",
        "ten": "DỊCH VỤ LƯU TRÚ VÀ ĂN UỐNG",
        "ten_ngan": "Dịch vụ lưu trú và ăn uống",
        "tu_khoa": ["lưu trú", "khách sạn", "nhà nghỉ", "du lịch", "ăn uống", "nhà hàng",
                    "kinh doanh dịch vụ ăn uống", "vệ sinh an toàn thực phẩm"],
    },
    {
        "ma": "J",
        "ten": "THÔNG TIN VÀ TRUYỀN THÔNG",
        "ten_ngan": "Thông tin và truyền thông",
        "tu_khoa": ["viễn thông", "công nghệ thông tin", "phần mềm", "internet", "an toàn thông tin",
                    "an ninh mạng", "dữ liệu cá nhân", "chữ ký số", "xuất bản", "báo chí",
                    "phát thanh", "truyền hình", "tần số vô tuyến"],
    },
    {
        "ma": "K",
        "ten": "HOẠT ĐỘNG TÀI CHÍNH, NGÂN HÀNG VÀ BẢO HIỂM",
        "ten_ngan": "Tài chính, ngân hàng và bảo hiểm",
        "tu_khoa": ["ngân hàng", "tổ chức tín dụng", "tín dụng", "cho vay", "lãi suất",
                    "ngoại hối", "chứng khoán", "trái phiếu", "bảo hiểm", "tái bảo hiểm",
                    "thanh toán không dùng tiền mặt", "phòng chống rửa tiền"],
    },
    {
        "ma": "L",
        "ten": "HOẠT ĐỘNG KINH DOANH BẤT ĐỘNG SẢN",
        "ten_ngan": "Kinh doanh bất động sản",
        "tu_khoa": ["bất động sản", "kinh doanh bất động sản", "nhà ở", "nhà ở thương mại",
                    "đất đai", "quyền sử dụng đất", "sàn giao dịch bất động sản",
                    "môi giới bất động sản", "chung cư", "dự án nhà ở"],
    },
    {
        "ma": "M",
        "ten": "HOẠT ĐỘNG CHUYÊN MÔN, KHOA HỌC VÀ CÔNG NGHỆ",
        "ten_ngan": "Chuyên môn, khoa học và công nghệ",
        "tu_khoa": ["kế toán", "kiểm toán", "tư vấn quản lý", "kiến trúc", "thiết kế",
                    "nghiên cứu khoa học", "phát triển công nghệ", "sở hữu trí tuệ",
                    "tiêu chuẩn đo lường chất lượng", "giám định", "luật sư", "công chứng"],
    },
    {
        "ma": "N",
        "ten": "HOẠT ĐỘNG HÀNH CHÍNH VÀ DỊCH VỤ HỖ TRỢ",
        "ten_ngan": "Hành chính và dịch vụ hỗ trợ",
        # "du lịch" đứng ở cả I (lưu trú, ăn uống) và N (đại lý, tua du lịch) —
        # VSIC tách hai nhánh này nhưng Luật Du lịch điều chỉnh cả hai, nên gán
        # cho cả hai ngành là đúng chứ không phải trùng lặp.
        "tu_khoa": ["du lịch", "lữ hành", "đại lý du lịch", "hướng dẫn viên du lịch",
                    "cho thuê lại lao động", "dịch vụ việc làm", "giới thiệu việc làm",
                    "xuất khẩu lao động", "đưa người lao động đi làm việc ở nước ngoài",
                    "dịch vụ bảo vệ", "vệ sinh công nghiệp", "tổ chức sự kiện",
                    "cho thuê máy móc", "dịch vụ hỗ trợ doanh nghiệp"],
    },
    {
        "ma": "O",
        "ten": "HOẠT ĐỘNG CỦA ĐẢNG CỘNG SẢN, TỔ CHỨC CHÍNH TRỊ - XÃ HỘI, QUẢN LÝ NHÀ NƯỚC, "
               "AN NINH QUỐC PHÒNG; BẢO ĐẢM XÃ HỘI BẮT BUỘC",
        "ten_ngan": "Quản lý nhà nước, an ninh quốc phòng",
        "tu_khoa": ["quản lý nhà nước", "thủ tục hành chính", "phân cấp", "phân quyền",
                    "cán bộ công chức", "viên chức", "an ninh quốc phòng", "bảo hiểm xã hội bắt buộc",
                    "tổ chức bộ máy"],
    },
    {
        "ma": "P",
        "ten": "GIÁO DỤC VÀ ĐÀO TẠO",
        "ten_ngan": "Giáo dục và đào tạo",
        "tu_khoa": ["giáo dục", "đào tạo", "trường học", "giáo viên", "học sinh", "sinh viên",
                    "đại học", "giáo dục nghề nghiệp", "học phí", "chương trình giáo dục",
                    "kiểm định chất lượng giáo dục"],
    },
    {
        "ma": "Q",
        "ten": "Y TẾ VÀ HOẠT ĐỘNG TRỢ GIÚP XÃ HỘI",
        "ten_ngan": "Y tế và trợ giúp xã hội",
        "tu_khoa": ["y tế", "khám bệnh", "chữa bệnh", "bệnh viện", "cơ sở y tế", "dược",
                    "thuốc", "trang thiết bị y tế", "bảo hiểm y tế", "an toàn thực phẩm",
                    "trợ giúp xã hội", "phòng chống dịch"],
    },
    {
        "ma": "R",
        "ten": "NGHỆ THUẬT, VUI CHƠI VÀ GIẢI TRÍ",
        "ten_ngan": "Nghệ thuật, vui chơi và giải trí",
        "tu_khoa": ["nghệ thuật biểu diễn", "điện ảnh", "thư viện", "bảo tàng", "di sản văn hóa",
                    "thể dục thể thao", "vui chơi giải trí", "trò chơi điện tử", "xổ số",
                    "casino", "đặt cược"],
    },
    {
        "ma": "S",
        "ten": "HOẠT ĐỘNG DỊCH VỤ KHÁC",
        "ten_ngan": "Dịch vụ khác",
        "tu_khoa": ["hiệp hội", "tổ chức xã hội - nghề nghiệp", "tổ chức xã hội nghề nghiệp",
                    "quỹ xã hội", "quỹ từ thiện", "tổ chức phi chính phủ",
                    "dịch vụ sửa chữa", "dịch vụ phục vụ cá nhân", "tang lễ",
                    "nghĩa trang", "mai táng", "hội quần chúng"],
    },
    {
        "ma": "T",
        "ten": "HOẠT ĐỘNG LÀM THUÊ CÁC CÔNG VIỆC TRONG CÁC HỘ GIA ĐÌNH, SẢN XUẤT SẢN PHẨM "
               "VẬT CHẤT VÀ DỊCH VỤ TỰ TIÊU DÙNG CỦA HỘ GIA ĐÌNH",
        "ten_ngan": "Lao động trong hộ gia đình",
        "tu_khoa": ["giúp việc gia đình", "lao động giúp việc", "người giúp việc",
                    "hợp đồng lao động giúp việc", "lao động tại nhà"],
    },
    {
        "ma": "U",
        "ten": "HOẠT ĐỘNG CỦA CÁC TỔ CHỨC VÀ CƠ QUAN QUỐC TẾ",
        "ten_ngan": "Tổ chức và cơ quan quốc tế",
        "tu_khoa": ["tổ chức quốc tế", "cơ quan đại diện ngoại giao", "điều ước quốc tế",
                    "tổ chức phi chính phủ nước ngoài", "viện trợ"],
    },
]

# Tra nhanh theo mã
BY_CODE: dict[str, Nganh] = {n["ma"]: n for n in VSIC_LEVEL1}

# Giữ nguyên hình dạng {tên ngành: [từ khoá]} để phần còn lại của hệ thống
# (industry_search, classify_industries, bot Telegram) không phải sửa.
INDUSTRY_MAP: dict[str, list[str]] = {n["ten_ngan"]: n["tu_khoa"] for n in VSIC_LEVEL1}


def code_of(ten_ngan: str) -> str:
    """Mã VSIC cấp 1 của một ngành theo tên ngắn."""
    for n in VSIC_LEVEL1:
        if n["ten_ngan"] == ten_ngan:
            return n["ma"]
    return ""


def official_name(ten_ngan: str) -> str:
    """Tên đầy đủ theo Quyết định 27/2018/QĐ-TTg."""
    for n in VSIC_LEVEL1:
        if n["ten_ngan"] == ten_ngan:
            return n["ten"]
    return ten_ngan
