"""
Tầng 3 của phễu — hỏi mô hình "ai cầm bút điền biểu mẫu này".

Chỉ chạy trên phần tầng 2 không dám kết luận. Đầu vào là tiêu đề, căn cứ và khối
ĐẦU ruột mẫu: khối đó luôn tự khai đối tượng ("Đơn vị báo cáo: Kho bạc Nhà nước",
"Tên doanh nghiệp: …"), nên không cần nạp cả biểu mẫu vào mô hình.

CACHE NẰM Ở `legal_forms.body_hash`, KHÔNG PHẢI BẢNG RIÊNG. Ruột mẫu không đổi
thì kết luận không đổi, mà `luu_bieu_mau()` đã xoá nhãn cũ mỗi khi hash đổi. Thêm
một bảng cache nữa chỉ tạo ra chỗ thứ hai để hai bên lệch nhau.

MÔ HÌNH TRẢ NHÃN, KHÔNG TRẢ VĂN XUÔI. Nhãn nằm ngoài tập đóng bị coi là "khac"
chứ không được tạo nhóm mới: `nghiep_vu` là mục lục của trang công khai và menu
lệnh Telegram, biên trôi thì mục lục vỡ.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from src.config import form_classifier_max_tokens, form_classifier_model
from src.legal.form_taxonomy import (
    CA_NHAN,
    CO_QUAN_NHA_NUOC,
    DOANH_NGHIEP,
    KHAC,
    NGHIEP_VU,
    chuan_hoa_nghiep_vu,
)
from src.rag.reports.llm import LLMUnavailable, call_report_llm

logger = logging.getLogger(__name__)

#: Bao nhiêu ký tự đầu ruột mẫu đưa cho mô hình. Đủ để phủ trọn khối tự khai của
#: mọi mẫu đã đo, mà vẫn giữ mỗi lượt gọi ở mức rẻ.
KY_TU_CHO_MO_HINH = 1800

_DOI_TUONG_HOP_LE = {DOANH_NGHIEP, CO_QUAN_NHA_NUOC, CA_NHAN, KHAC}

SYSTEM_PROMPT = """\
Bạn phân loại biểu mẫu pháp lý Việt Nam cho một hệ thống tra cứu dành cho CHỦ \
DOANH NGHIỆP.

Với mỗi biểu mẫu, trả lời đúng một câu hỏi: AI LÀ NGƯỜI CẦM BÚT ĐIỀN VÀO TỜ NÀY?

- doanh_nghiep: doanh nghiệp, hộ kinh doanh, hợp tác xã, hoặc người đại diện của \
họ điền để nộp cho cơ quan nhà nước, cho đối tác, hoặc cho người lao động.
- co_quan_nha_nuoc: cán bộ của cơ quan nhà nước, đơn vị sự nghiệp công lập điền \
trong nội bộ bộ máy (báo cáo ngân sách, quyết định hành chính, biên bản kiểm tra \
do đoàn kiểm tra lập, giấy phép do cơ quan CẤP).
- ca_nhan: cá nhân điền cho việc riêng, không nhân danh hoạt động kinh doanh \
(hộ tịch, khiếu nại cá nhân, trợ cấp xã hội).
- khac: không đủ căn cứ để xếp.

PHÂN BIỆT QUAN TRỌNG. Một tờ giấy phép có hai mặt: ĐƠN ĐỀ NGHỊ CẤP giấy phép là \
doanh nghiệp điền; MẪU GIẤY PHÉP mà cơ quan cấp ra là cơ quan nhà nước điền. Đọc \
kỹ khối đầu để biết đang là mặt nào.

Doanh nghiệp nhà nước VẪN LÀ doanh nghiệp.

Sau đó gắn nhóm nghiệp vụ, chỉ chọn trong danh sách cho sẵn, tối đa 2 nhóm.

Trả về DUY NHẤT một khối JSON, không giải thích gì thêm:
{"nguoi_dien": "...", "do_tin_cay": 0.0, "nhom_nghiep_vu": ["..."], "ly_do": "..."}

`do_tin_cay` từ 0 đến 1. `ly_do` tối đa 25 từ, tiếng Việt."""


@dataclass
class KetQuaPhanLoai:
    audience: str
    confidence: float = 0.0
    nghiep_vu: list[str] = field(default_factory=list)
    ly_do: str = ""


def _danh_sach_nghiep_vu() -> str:
    return "\n".join(f"- {ma}: {ten}" for ma, ten in NGHIEP_VU.items())


def dung_prompt(tieu_de: str, ruot_text: str, can_cu: list[str] | None = None,
                linh_vuc: str = "") -> str:
    khoi = [f"TIÊU ĐỀ: {tieu_de}"]
    if linh_vuc:
        khoi.append(f"LĨNH VỰC: {linh_vuc}")
    if can_cu:
        khoi.append("CĂN CỨ: " + ", ".join(can_cu[:4]))
    khoi.append("NHÓM NGHIỆP VỤ HỢP LỆ:\n" + _danh_sach_nghiep_vu())
    khoi.append(
        "KHỐI ĐẦU BIỂU MẪU:\n" + (ruot_text or "")[:KY_TU_CHO_MO_HINH]
    )
    return "\n\n".join(khoi)


def _boc_json(raw: str) -> dict:
    """Lấy khối JSON đầu tiên trong phản hồi.

    Mô hình rẻ hay kèm một câu dẫn trước JSON dù prompt đã cấm. Bóc bằng dấu
    ngoặc thay vì `json.loads` thẳng, để một câu thừa không làm hỏng cả lượt gọi
    đã trả tiền.
    """
    s = (raw or "").strip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        raise ValueError(f"Phản hồi không có JSON: {s[:200]}")
    return json.loads(m.group(0))


def phan_loai(tieu_de: str, ruot_text: str, can_cu: list[str] | None = None,
              linh_vuc: str = "", goi_mo_hinh=call_report_llm) -> KetQuaPhanLoai:
    """Hỏi mô hình. Ném LLMUnavailable khi không gọi được — KHÔNG đoán bừa.

    `goi_mo_hinh` tiêm được để test chạy không cần khoá API và không tốn tiền.

    Nhãn lạ rơi về "khac" thay vì làm hỏng lượt gọi: mô hình trả "doanh_nghiep_"
    hay "Doanh Nghiệp" là chuyện thường, mà một mẫu bị xếp "khac" thì chỉ nằm chờ
    người duyệt, còn ném lỗi thì cả lô dừng.
    """
    kq_llm = goi_mo_hinh(
        SYSTEM_PROMPT,
        dung_prompt(tieu_de, ruot_text, can_cu, linh_vuc),
        model=form_classifier_model(),
        max_tokens=form_classifier_max_tokens(),
    )
    data = _boc_json(kq_llm.text)

    doi_tuong = str(data.get("nguoi_dien", "")).strip().lower().replace(" ", "_")
    if doi_tuong not in _DOI_TUONG_HOP_LE:
        logger.info("Mô hình trả nhãn lạ %r cho %r — xếp vào 'khac'",
                    doi_tuong, tieu_de[:60])
        doi_tuong = KHAC

    try:
        tin_cay = float(data.get("do_tin_cay", 0) or 0)
    except (TypeError, ValueError):
        tin_cay = 0.0

    return KetQuaPhanLoai(
        audience=doi_tuong,
        confidence=min(max(tin_cay, 0.0), 1.0),
        nghiep_vu=chuan_hoa_nghiep_vu(data.get("nhom_nghiep_vu") or []),
        ly_do=str(data.get("ly_do", ""))[:300],
    )


__all__ = [
    "KY_TU_CHO_MO_HINH", "SYSTEM_PROMPT", "KetQuaPhanLoai",
    "dung_prompt", "phan_loai", "LLMUnavailable",
]
