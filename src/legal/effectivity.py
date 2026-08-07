"""
Cờ hiệu lực chuẩn hoá.

VÌ SAO CẦN CHUẨN HOÁ: `eff_status` là chuỗi tự do do Bộ Tư pháp ghi, hiện có 6
giá trị khác nhau kể cả rỗng. Mọi nơi cần biết "văn bản này còn hiệu lực không"
đều phải so chuỗi bằng Python sau khi đã tải dữ liệu về (xem
`graph_traversal.validate_results`) — nghĩa là không lọc được ở tầng SQL. Đó là
lý do truy xuất phải lấy dư 60 đoạn rồi mới loại, và sau khi kho lớn lên vì bao
đóng dẫn chiếu thì phần lớn 60 chỗ đó sẽ bị văn bản đã chết chiếm mất.

VÌ SAO eff_state_as_of LÀ BẮT BUỘC: "còn hiệu lực" không phải thuộc tính vĩnh
viễn của văn bản mà là khẳng định tại một thời điểm. Một văn bản có `eff_to` là
ngày mai thì hôm nay còn hiệu lực, ngày kia thì không. Lưu cờ mà không lưu mốc
tính là biến một khẳng định có điều kiện thành một lời nói dối kể từ hôm sau.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

CHUA_HIEU_LUC = "chua_hieu_luc"
CON_HIEU_LUC = "con_hieu_luc"
HET_MOT_PHAN = "het_mot_phan"
HET_TOAN_BO = "het_toan_bo"
KHONG_RO = "khong_ro"

# Trạng thái coi như không còn dùng làm căn cứ pháp lý được nữa.
DEAD_STATES = frozenset({HET_TOAN_BO})

# Trạng thái dùng được nhưng phải kèm cảnh báo trong báo cáo.
WARN_STATES = frozenset({HET_MOT_PHAN, CHUA_HIEU_LUC, KHONG_RO})

# Chuỗi tự do của Bộ Tư pháp → cờ chuẩn hoá. Khớp theo tiền tố đã thường hoá để
# chịu được khác biệt dấu câu và khoảng trắng.
_BY_TEXT: tuple[tuple[str, str], ...] = (
    ("hết hiệu lực toàn bộ", HET_TOAN_BO),
    ("hết hiệu lực một phần", HET_MOT_PHAN),
    ("hết hiệu lực", HET_TOAN_BO),
    ("chưa có hiệu lực", CHUA_HIEU_LUC),
    ("còn hiệu lực", CON_HIEU_LUC),
    ("chưa xác định", KHONG_RO),
)


@dataclass(frozen=True)
class Effectivity:
    state: str
    as_of: date
    source: str  # "trang_thai" | "ngay_thang" | "khong_ro"


def _from_text(eff_status: str | None) -> str | None:
    text = " ".join((eff_status or "").split()).lower()
    if not text:
        return None
    for needle, state in _BY_TEXT:
        if needle in text:
            return state
    return None


def _from_dates(eff_from: date | None, eff_to: date | None, as_of: date) -> str | None:
    """Suy từ mốc ngày khi nguồn không nói gì về trạng thái.

    Chỉ kết luận khi ngày tháng thực sự cho phép: có eff_to đã qua thì chắc chắn
    hết hiệu lực, có eff_from ở tương lai thì chắc chắn chưa. Trường hợp còn lại
    (chỉ có eff_from trong quá khứ) KHÔNG kết luận "còn hiệu lực" — văn bản có
    thể đã bị bãi bỏ mà nguồn chưa cập nhật eff_to.
    """
    if eff_to and eff_to <= as_of:
        return HET_TOAN_BO
    if eff_from and eff_from > as_of:
        return CHUA_HIEU_LUC
    return None


def resolve(
    eff_status: str | None,
    eff_from: date | None,
    eff_to: date | None,
    as_of: date,
) -> Effectivity:
    """Cờ hiệu lực tại một thời điểm, kèm mốc tính và căn cứ đã dùng.

    Thứ tự ưu tiên: trạng thái do nguồn công bố → suy từ ngày tháng → không rõ.
    Không bao giờ mặc định "còn hiệu lực": với báo cáo tuân thủ, khẳng định một
    văn bản đang có hiệu lực mà không có căn cứ chính là bịa dữ kiện pháp lý.
    """
    state = _from_text(eff_status)
    if state:
        # Trạng thái nguồn ghi "còn hiệu lực" nhưng eff_to đã qua thì ngày tháng
        # thắng: bảng trạng thái được cập nhật thủ công nên hay trễ.
        if state == CON_HIEU_LUC and eff_to and eff_to <= as_of:
            return Effectivity(HET_TOAN_BO, as_of, "ngay_thang")
        return Effectivity(state, as_of, "trang_thai")

    state = _from_dates(eff_from, eff_to, as_of)
    if state:
        return Effectivity(state, as_of, "ngay_thang")

    return Effectivity(KHONG_RO, as_of, "khong_ro")


def label(state: str) -> str:
    """Nhãn tiếng Việt để hiển thị trong note và báo cáo."""
    return {
        CHUA_HIEU_LUC: "Chưa có hiệu lực",
        CON_HIEU_LUC: "Còn hiệu lực",
        HET_MOT_PHAN: "Hết hiệu lực một phần",
        HET_TOAN_BO: "Hết hiệu lực toàn bộ",
        KHONG_RO: "Chưa xác minh được hiệu lực",
    }.get(state, "Chưa xác minh được hiệu lực")
