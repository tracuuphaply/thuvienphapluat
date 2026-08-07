"""
Đơn vị hành chính cấp tỉnh, có tính tới đợt sắp xếp năm 2025.

NGUỒN: Nghị quyết 202/2025/QH15 ngày 12/6/2025 của Quốc hội về sắp xếp đơn vị
hành chính cấp tỉnh, hiệu lực 12/6/2025, chính quyền mới hoạt động từ 01/7/2025.
Kết quả: 34 đơn vị cấp tỉnh (28 tỉnh + 6 thành phố trực thuộc trung ương), gồm
23 đơn vị hình thành sau sắp xếp (19 tỉnh + 4 thành phố) và 11 đơn vị giữ nguyên.
Bảng dưới đã được đối chiếu ngược: 34 đơn vị hiện hành + 29 tên bị nhập = 63 tên
cũ, đúng bằng số tỉnh thành trước sắp xếp.

VÌ SAO PHẢI GIỮ CẢ TÊN CŨ: kho văn bản trải từ 2015 đến nay, nên cùng một địa
bàn xuất hiện dưới hai tên khác nhau tuỳ thời điểm ban hành. Tra cứu "Bình Dương"
mà không có bản đồ này sẽ im lặng bỏ sót toàn bộ văn bản nay thuộc TP. Hồ Chí
Minh — báo cáo cho doanh nghiệp ở đó sẽ thiếu đúng phần luật đang điều chỉnh họ.

VỀ MÃ TỈNH: dùng slug từ tên tiếng Việt (`ho-chi-minh`) chứ không dùng mã số
hành chính hai chữ số. Mã số phải tra từ văn bản gốc; slug thì tự kiểm chứng
được bằng mắt và không có nguy cơ ghi nhầm một con số mà về sau không ai soát.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Huế đổi tên trước đợt sắp xếp: "tỉnh Thừa Thiên Huế" thành "thành phố Huế"
# trực thuộc trung ương theo Nghị quyết 175/2024/QH15, từ 01/01/2025.
_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "Huế": ("Thừa Thiên Huế", "Thừa Thiên - Huế"),
    "Hồ Chí Minh": ("TP Hồ Chí Minh", "TP. Hồ Chí Minh", "TPHCM", "Sài Gòn"),
    "Bà Rịa - Vũng Tàu": ("Bà Rịa Vũng Tàu", "Bà Rịa-Vũng Tàu",),
}


@dataclass(frozen=True)
class Province:
    code: str            # slug, ví dụ "ho-chi-minh"
    name: str            # tên hiện hành
    is_city: bool        # thành phố trực thuộc trung ương
    absorbed: tuple[str, ...] = field(default=())  # tên các tỉnh cũ đã nhập vào


# 34 đơn vị hiện hành. `absorbed` chỉ liệt kê tên BỊ MẤT sau sắp xếp — tên của
# chính đơn vị nhận thì đã nằm ở `name`.
PROVINCES: tuple[Province, ...] = (
    # ── Thành phố trực thuộc trung ương (6) ──
    Province("ha-noi", "Hà Nội", True),
    Province("hue", "Huế", True),
    Province("hai-phong", "Hải Phòng", True, ("Hải Dương",)),
    Province("da-nang", "Đà Nẵng", True, ("Quảng Nam",)),
    Province("ho-chi-minh", "Hồ Chí Minh", True, ("Bình Dương", "Bà Rịa - Vũng Tàu")),
    Province("can-tho", "Cần Thơ", True, ("Sóc Trăng", "Hậu Giang")),
    # ── Tỉnh giữ nguyên (9) ──
    Province("cao-bang", "Cao Bằng", False),
    Province("dien-bien", "Điện Biên", False),
    Province("ha-tinh", "Hà Tĩnh", False),
    Province("lai-chau", "Lai Châu", False),
    Province("lang-son", "Lạng Sơn", False),
    Province("nghe-an", "Nghệ An", False),
    Province("quang-ninh", "Quảng Ninh", False),
    Province("son-la", "Sơn La", False),
    Province("thanh-hoa", "Thanh Hóa", False),
    # ── Tỉnh hình thành sau sắp xếp (19) ──
    Province("tuyen-quang", "Tuyên Quang", False, ("Hà Giang",)),
    Province("lao-cai", "Lào Cai", False, ("Yên Bái",)),
    Province("thai-nguyen", "Thái Nguyên", False, ("Bắc Kạn",)),
    Province("phu-tho", "Phú Thọ", False, ("Vĩnh Phúc", "Hòa Bình")),
    Province("bac-ninh", "Bắc Ninh", False, ("Bắc Giang",)),
    Province("hung-yen", "Hưng Yên", False, ("Thái Bình",)),
    Province("ninh-binh", "Ninh Bình", False, ("Hà Nam", "Nam Định")),
    Province("quang-tri", "Quảng Trị", False, ("Quảng Bình",)),
    Province("quang-ngai", "Quảng Ngãi", False, ("Kon Tum",)),
    Province("gia-lai", "Gia Lai", False, ("Bình Định",)),
    Province("khanh-hoa", "Khánh Hòa", False, ("Ninh Thuận",)),
    Province("lam-dong", "Lâm Đồng", False, ("Đắk Nông", "Bình Thuận")),
    Province("dak-lak", "Đắk Lắk", False, ("Phú Yên",)),
    Province("dong-nai", "Đồng Nai", False, ("Bình Phước",)),
    Province("tay-ninh", "Tây Ninh", False, ("Long An",)),
    Province("vinh-long", "Vĩnh Long", False, ("Bến Tre", "Trà Vinh")),
    Province("dong-thap", "Đồng Tháp", False, ("Tiền Giang",)),
    Province("ca-mau", "Cà Mau", False, ("Bạc Liêu",)),
    Province("an-giang", "An Giang", False, ("Kiên Giang",)),
)


def _norm(text: str) -> str:
    """Bỏ dấu, thường hoá, gộp khoảng trắng — để so tên bất kể cách viết."""
    text = (text or "").translate(str.maketrans({"Đ": "D", "đ": "d"}))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text)
    return " ".join(text.lower().split())


def _build_lookup() -> dict[str, tuple[str, str]]:
    """Tên (đã chuẩn hoá) → (mã như văn bản ghi, mã hiện hành).

    Tên cũ trỏ về mã của chính nó để giữ đúng điều văn bản viết, đồng thời trỏ
    tới mã hiện hành để tra cứu theo địa bàn ngày nay vẫn ra kết quả.
    """
    table: dict[str, tuple[str, str]] = {}
    for p in PROVINCES:
        for alias in (p.name, *_EXTRA_ALIASES.get(p.name, ())):
            table[_norm(alias)] = (p.code, p.code)
        for old in p.absorbed:
            old_code = _slug(old)
            for alias in (old, *_EXTRA_ALIASES.get(old, ())):
                table[_norm(alias)] = (old_code, p.code)
    return table


def _slug(name: str) -> str:
    return _norm(name).replace(" ", "-")


_LOOKUP = _build_lookup()

# Tên tỉnh đứng sau các tiền tố này trong agency_name của Bộ Tư pháp.
# Dữ liệu nguồn bẩn: có cả "UBND Thành phố Đồng Nai" trong khi Đồng Nai là tỉnh,
# nên phải bỏ tiền tố rồi khớp theo TÊN, không tin vào chữ "Tỉnh"/"Thành phố".
_AGENCY_PREFIX = re.compile(
    r"^\s*(UBND|HĐND|Ủy ban nhân dân|Hội đồng nhân dân)\s*"
    r"(tỉnh|thành phố|tp\.?)?\s*",
    re.IGNORECASE,
)

_LOCAL_AGENCY = re.compile(
    r"^\s*(UBND|HĐND|Ủy ban nhân dân|Hội đồng nhân dân)\b", re.IGNORECASE
)


def is_local_agency(agency_name: str) -> bool:
    return bool(_LOCAL_AGENCY.match(agency_name or ""))


def province_from_agency(agency_name: str) -> tuple[str | None, str | None]:
    """(mã như văn bản ghi, mã hiện hành) suy từ tên cơ quan ban hành.

    (None, None) khi không phải cơ quan địa phương hoặc không khớp tên nào —
    không đoán, vì gán nhầm địa bàn nghĩa là báo cáo cho doanh nghiệp ở tỉnh A
    dẫn quy định chỉ áp dụng ở tỉnh B.
    """
    if not is_local_agency(agency_name):
        return None, None
    remainder = _AGENCY_PREFIX.sub("", agency_name or "")
    return _LOOKUP.get(_norm(remainder), (None, None))


def province_name(code: str | None) -> str:
    """Tên hiển thị của một mã; chính mã đó nếu là tên tỉnh cũ đã bị nhập."""
    if not code:
        return ""
    for p in PROVINCES:
        if p.code == code:
            return p.name
        for old in p.absorbed:
            if _slug(old) == code:
                return old
    return code


def current_code(code: str | None) -> str | None:
    """Mã hiện hành của một địa bàn, sau khi áp bản đồ sắp xếp 2025."""
    if not code:
        return None
    for p in PROVINCES:
        if p.code == code:
            return p.code
        for old in p.absorbed:
            if _slug(old) == code:
                return p.code
    return None
