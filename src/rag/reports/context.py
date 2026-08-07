"""
Dựng khối dữ liệu nạp cho mô hình — dùng chung cho cả ba loại báo cáo.

Năm khoá đầu là hợp đồng dữ liệu đã có từ trước; hai khoá cuối là phần bổ sung
của giai đoạn này:

    thong_tin_tra_cuu             tóm tắt số lượng
    han_che_du_lieu               chỗ nào thiếu — BẮT BUỘC công bố trong báo cáo
    danh_sach_van_ban             metadata từng văn bản
    chi_tiet_dieu_khoan_chunks    trích đoạn điều khoản
    do_thi_quan_he_van_ban_edges  quan hệ hai chiều
    diem_tac_dong_nganh           điểm % tác động 21 ngành VSIC
    van_ban_bi_tac_dong           văn bản cũ bị sửa/thay thế, để so được thay đổi
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from src.legal import effectivity
from src.legal.hierarchy import LEVEL_NON_NORMATIVE
from src.legal.provinces import province_name
from src.obsidian.config_obsidian import HIERARCHY_LABELS
from src.obsidian.vsic import BY_CODE
from src.storage.models import Document, DocumentReference

logger = logging.getLogger(__name__)


@dataclass
class ReportContext:
    payload: dict[str, Any] = field(default_factory=dict)
    doc_nums: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.payload.get("danh_sach_van_ban")


def document_facts(doc: Document, thieu_trang_thai: list[str]) -> dict[str, Any]:
    """Metadata một văn bản, ở dạng mô hình đọc được.

    Không mặc định "Còn hiệu lực" khi nguồn không nói gì: với báo cáo tuân thủ,
    đó là bịa dữ kiện pháp lý. Đúng lỗi từng khiến 25% kho được khẳng định là
    luật hiện hành mà không có căn cứ nào.
    """
    if not doc.eff_status:
        thieu_trang_thai.append(doc.doc_num)

    level = doc.hierarchy_level
    level = LEVEL_NON_NORMATIVE if level is None else int(level)
    state = doc.eff_state or effectivity.KHONG_RO

    return {
        "doc_num": doc.doc_num,
        "title": doc.title,
        "doc_type": doc.doc_type,
        # Mục "xử lý mâu thuẫn theo thứ bậc" của prompt cần đúng hai trường này;
        # trước đây mô hình chỉ nhận chuỗi doc_type và phải tự đoán cấp nào cao hơn.
        "cap_hieu_luc_phap_ly": level,
        "cap_hieu_luc_dien_giai": HIERARCHY_LABELS.get(
            level, HIERARCHY_LABELS[LEVEL_NON_NORMATIVE]
        ),
        "la_van_ban_qppl": bool(doc.is_vbqppl),
        "pham_vi_lanh_tho": doc.territorial_scope or "khong_xac_dinh",
        "dia_ban_ap_dung": province_name(doc.province_code_current),
        "issue_date": str(doc.issue_date) if doc.issue_date else "",
        "eff_from": str(doc.eff_from) if doc.eff_from else "",
        "eff_to": str(doc.eff_to) if doc.eff_to else "",
        "eff_status": doc.eff_status or "Chưa xác định",
        "tinh_trang_hieu_luc_chuan_hoa": effectivity.label(state),
        "hieu_luc_tinh_den_ngay": str(doc.eff_state_as_of) if doc.eff_state_as_of else "",
        "agency_name": doc.agency_name or "",
        "field_name": doc.field_name or "",
    }


def graph_edges(session, doc: Document) -> list[dict[str, Any]]:
    """Quan hệ dẫn chiếu theo CẢ HAI CHIỀU.

    Chỉ lấy chiều xuôi thì không bao giờ biết văn bản này đang bị ai sửa đổi hay
    bãi bỏ — đúng câu hỏi quan trọng nhất khi thẩm định hiệu lực.
    """
    edges: list[dict[str, Any]] = []

    for ref in session.query(DocumentReference).filter(
        DocumentReference.source_doc_id == doc.id
    ).all():
        edges.append({
            "source_doc_num": doc.doc_num,
            "target_doc_num": ref.target_doc_num,
            "relation_type": ref.relation_type,
            "chieu": "văn bản này tác động lên",
        })

    for ref in session.query(DocumentReference).filter(
        DocumentReference.target_doc_num == doc.doc_num
    ).all():
        src = session.query(Document).filter(Document.id == ref.source_doc_id).first()
        edges.append({
            "source_doc_num": src.doc_num if src else "",
            "target_doc_num": doc.doc_num,
            "relation_type": ref.relation_type,
            "chieu": "văn bản này BỊ tác động bởi",
        })

    return edges


def industry_impact(session, doc_keys: list[str], version: str,
                    min_pct_doc: float = 1.0) -> list[dict[str, Any]]:
    """Điểm tác động ngành của một nhóm văn bản.

    Lọc bỏ ngành có tỷ trọng dưới ngưỡng: 21 dòng cho mỗi văn bản, phần lớn gần
    0, chỉ làm loãng ngữ cảnh và tốn token.
    """
    if not doc_keys:
        return []

    placeholders = ",".join(f":k{i}" for i in range(len(doc_keys)))
    params: dict[str, Any] = {"v": version, "min": min_pct_doc}
    params.update({f"k{i}": key for i, key in enumerate(doc_keys)})

    rows = session.execute(text(f"""
        SELECT doc_num, vsic_code, impact_pct_doc, impact_pct_industry
        FROM document_industry_impact
        WHERE scorer_version = :v
          AND doc_key IN ({placeholders})
          AND impact_pct_doc >= :min
        ORDER BY doc_num, impact_pct_doc DESC
    """), params).mappings().all()

    return [{
        "doc_num": r["doc_num"],
        "ma_nganh": r["vsic_code"],
        "ten_nganh": BY_CODE.get(r["vsic_code"], {}).get("ten_ngan", r["vsic_code"]),
        "ty_trong_tac_dong": round(r["impact_pct_doc"], 1),
        "cuong_do_tac_dong": round(r["impact_pct_industry"], 1),
    } for r in rows]


def limitations(
    thieu_trang_thai: list[str],
    thieu_metadata: list[str],
    loai_do_het_hieu_luc: int = 0,
    ghi_chu_thoi_gian: str = "",
) -> dict[str, Any]:
    """Khối hạn chế dữ liệu — mô hình BẮT BUỘC công bố ở phụ lục.

    Đây là thứ giữ cho báo cáo trung thực khi dữ liệu thiếu, thay vì im lặng lấp
    bằng kiến thức nền.
    """
    return {
        "so_van_ban_khong_ro_trang_thai_hieu_luc": len(thieu_trang_thai),
        "danh_sach_khong_ro_trang_thai": thieu_trang_thai,
        "so_doan_bi_loai_vi_van_ban_het_hieu_luc": loai_do_het_hieu_luc,
        "so_van_ban_thieu_metadata": len(thieu_metadata),
        "danh_sach_thieu_metadata": thieu_metadata,
        "pham_vi_thoi_gian_thuc_te": ghi_chu_thoi_gian,
    }
