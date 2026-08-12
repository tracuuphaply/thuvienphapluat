"""
Bộ lọc "văn bản liên quan doanh nghiệp" cho báo cáo.

Mục tiêu báo cáo là giúp CHỦ DOANH NGHIỆP cập nhật luật phục vụ hoạt động kinh
doanh. Kho lại chứa cả văn bản y tế, giáo dục, văn hoá-xã hội và hàng trăm quyết
định cấp tỉnh — không thuộc mục tiêu đó. Một báo cáo "văn bản mới" mà nội dung là
quyết định bãi bỏ hỗ trợ khám chữa bệnh của một tỉnh thì đúng thể loại nhưng sai
người đọc. Bộ lọc này quyết định văn bản nào được đưa vào báo cáo.

HAI TIÊU CHÍ — phải thoả CẢ HAI:

  1. Lĩnh vực TVPL thuộc nhóm liên quan doanh nghiệp (`business_field_codes()`).
     Dựa trên `tvpl_field_code` — mã lĩnh vực đóng 1–27 của Thư viện Pháp luật,
     luôn có sẵn trên mỗi văn bản (xem src/legal/tvpl_fields.py).
  2. Cấp trung ương — `territorial_scope == 'trung_uong'`. Văn bản cấp tỉnh chỉ
     áp dụng ở một địa bàn, không phải cập nhật toàn quốc mà báo cáo hướng tới.
     Tắt được bằng REPORT_CENTRAL_ONLY=false.

Cả hai chỉnh được qua biến môi trường (xem src/config.py) để đổi định nghĩa
"liên quan doanh nghiệp" mà không phải sửa code.
"""
from __future__ import annotations

from src.config import business_field_codes_override, report_central_only

# 20 lĩnh vực: 16 cốt lõi + 4 nhóm ranh giới đã chọn (16 vi phạm hành chính,
# 19 tài chính nhà nước, 25 quyền dân sự, 13 dịch vụ pháp lý).
#
# LOẠI RA có chủ đích: 15 (bộ máy hành chính), 17 (trách nhiệm hình sự),
# 18 (thủ tục tố tụng), 22 (giáo dục), 24 (thể thao - y tế), 26 (văn hoá - xã
# hội), 27 (lĩnh vực khác). Đây là các nhóm mà chủ doanh nghiệp không đọc để
# phục vụ kinh doanh.
DEFAULT_BUSINESS_FIELD_CODES: frozenset[int] = frozenset(
    {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 19, 20, 21, 23, 25}
)

CENTRAL_SCOPE = "trung_uong"


def business_field_codes() -> frozenset[int]:
    """Bộ mã lĩnh vực coi là liên quan doanh nghiệp, sau khi áp override env."""
    raw = business_field_codes_override().strip()
    if not raw:
        return DEFAULT_BUSINESS_FIELD_CODES
    try:
        codes = {int(x) for x in raw.replace(";", ",").split(",") if x.strip()}
    except ValueError:
        return DEFAULT_BUSINESS_FIELD_CODES
    return frozenset(codes) or DEFAULT_BUSINESS_FIELD_CODES


def is_business_field(code: int | None) -> bool:
    return code in business_field_codes()


def is_business_document(tvpl_field_code: int | None,
                         territorial_scope: str | None) -> bool:
    """Văn bản có được đưa vào báo cáo cho chủ doanh nghiệp không."""
    if not is_business_field(tvpl_field_code):
        return False
    if report_central_only() and territorial_scope != CENTRAL_SCOPE:
        return False
    return True


def reason_excluded(tvpl_field_code: int | None,
                    territorial_scope: str | None) -> str:
    """Lý do loại — ghi vào SKIPPED để người vận hành biết vì sao vắng.

    Rỗng nghĩa là văn bản KHÔNG bị loại.
    """
    if not is_business_field(tvpl_field_code):
        return f"ngoai_linh_vuc_doanh_nghiep:{tvpl_field_code}"
    if report_central_only() and territorial_scope != CENTRAL_SCOPE:
        return f"khong_phai_trung_uong:{territorial_scope or 'khong_ro'}"
    return ""


def field_scope_by_key(session, doc_keys) -> dict[str, tuple]:
    """Tra (tvpl_field_code, territorial_scope) cho một loạt doc_key, một câu SQL."""
    from sqlalchemy import text

    keys = [k for k in doc_keys if k]
    if not keys:
        return {}
    ph = ",".join(f":k{i}" for i in range(len(keys)))
    params = {f"k{i}": k for i, k in enumerate(keys)}
    rows = session.execute(text(
        "SELECT doc_key, tvpl_field_code, territorial_scope FROM documents "
        f"WHERE doc_key IN ({ph})"
    ), params).mappings().all()
    return {r["doc_key"]: (r["tvpl_field_code"], r["territorial_scope"]) for r in rows}


def filter_business_doc_keys(session, doc_keys) -> list[str]:
    """Giữ lại doc_key thuộc nhóm liên quan doanh nghiệp, bỏ phần còn lại.

    Giữ nguyên thứ tự đầu vào để bên gọi không phải sắp lại.
    """
    meta = field_scope_by_key(session, doc_keys)
    out = []
    for k in doc_keys:
        field, scope = meta.get(k, (None, None))
        if is_business_document(field, scope):
            out.append(k)
    return out


def filter_business_docs(docs: list) -> list:
    """Lọc danh sách đối tượng Document theo hai tiêu chí (đọc thuộc tính thẳng)."""
    return [
        d for d in docs
        if is_business_document(
            getattr(d, "tvpl_field_code", None),
            getattr(d, "territorial_scope", None),
        )
    ]


__all__ = [
    "DEFAULT_BUSINESS_FIELD_CODES", "CENTRAL_SCOPE",
    "business_field_codes", "is_business_field", "is_business_document",
    "reason_excluded", "filter_business_doc_keys", "filter_business_docs",
    "field_scope_by_key",
]
