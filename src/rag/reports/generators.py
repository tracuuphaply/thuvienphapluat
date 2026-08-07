"""
Ba bộ sinh báo cáo.

    (a) generate_industry_report    tổng hợp pháp lý một ngành
    (b) generate_update_report      phân tích văn bản mới ban hành/có hiệu lực
    (c) generate_business_report    chuyên sâu cho doanh nghiệp trong ngành

(b) khác (a) ở chỗ căn bản: (a) làm việc trên KẾT QUẢ TÌM KIẾM còn (b) làm việc
trên một danh sách văn bản CỐ ĐỊNH đã biết trước, nên phải đọc hết chứ không
chọn lọc.

(c) khác cả hai: nó không truy xuất lại từ đầu mà tiêu thụ chính đầu ra của (b).
Truyền nguyên văn markdown của (b) vào ngữ cảnh là lựa chọn có chủ ý — nó bảo
đảm hai tài liệu khách nhận trong cùng một ngày không mâu thuẫn nhau, và mâu
thuẫn giữa hai tài liệu cùng ngày là thứ phá huỷ niềm tin nhanh nhất.
"""
from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.obsidian.vsic import code_of, official_name
from src.rag.db_rag import RAGDatabase
from src.rag.graph_traversal import validate_results
from src.rag.hybrid_search import industry_search
from src.rag.reports import context as ctx
from src.rag.reports.llm import LLMUnavailable, call_report_llm
from src.rag.reports.prompts import load_prompt
from src.storage.models import Document

logger = logging.getLogger(__name__)

DEFAULT_AUDIENCE = "Ban Lãnh đạo doanh nghiệp và Trưởng bộ phận pháp chế"

# ── Định nghĩa vận hành của "ngành bị ảnh hưởng nhiều" ──
#
# Phải thoả CẢ HAI điều kiện. Chỉ dùng cường độ là không đủ, và đây là lỗi đo
# được chứ không phải lo xa: Luật Xây dựng 2025 đạt cường độ ≥ 80 ở 18/21 ngành,
# nên sinh ra 18 báo cáo chuyên sâu — kể cả cho "Tổ chức và cơ quan quốc tế".
#
# Nguyên nhân: `impact_raw` tỷ lệ với TỔNG số ràng buộc của văn bản, nên một đạo
# luật 300 Điều đứng ở phân vị cao trong phân phối của MỌI ngành. Câu "văn bản
# này nằm trong top 15% văn bản tác động tới ngành T" đúng về số học nhưng vô
# nghĩa — nó nằm trong top 15% của mọi thứ.
C_THRESHOLD = 80.0          # cường độ: ngành này có nên quan tâm không
# Tỷ trọng: văn bản có THỰC SỰ nói về ngành này không. Mốc là mức mà phân bổ
# đều 21 ngành sẽ cho (100/21 ≈ 4,76%) — dưới mức đó nghĩa là ngành này nhận
# được ít hơn cả phần ngẫu nhiên.
C_MIN_SHARE = 100.0 / 21


@dataclass
class ReportResult:
    kind: str
    markdown: str
    payload: dict[str, Any] = field(default_factory=dict)
    sidecar: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    model: str = ""


def _header(lines: dict[str, str]) -> str:
    width = max(len(k) for k in lines) if lines else 0
    return "\n".join(f"{k.ljust(width)} : {v}" for k, v in lines.items())


def _user_message(header: dict[str, str], payload: dict[str, Any],
                  notes: list[str]) -> str:
    return (
        _header(header)
        + "\n\n=== DỮ LIỆU THỰC TẾ TRÍCH XUẤT TỪ CƠ SỞ DỮ LIỆU PHÁP LUẬT ===\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nLƯU Ý QUAN TRỌNG:\n"
        + "\n".join(f"{i}. {n}" for i, n in enumerate(notes, 1))
    )


# Nhắc lại ở message người dùng những điều dễ bị bỏ qua nhất. Prompt hệ thống đã
# nói, nhưng đây là các quy tắc mà vi phạm gây sai dữ kiện pháp lý.
COMMON_NOTES = [
    "Không tự bịa số hiệu văn bản nằm ngoài dữ liệu được cung cấp.",
    "Khối `han_che_du_lieu` là dữ kiện BẮT BUỘC phải công bố ở phụ lục. Văn bản "
    "có tình trạng hiệu lực 'Chưa xác minh được' phải ghi rõ là CHƯA XÁC MINH, "
    "không được trình bày như đang còn hiệu lực.",
    "Khi hai văn bản mâu thuẫn, dùng `cap_hieu_luc_phap_ly`: SỐ NHỎ HƠN LÀ HIỆU "
    "LỰC CAO HƠN. Văn bản có `la_van_ban_qppl` = false KHÔNG được dùng làm căn "
    "cứ pháp lý.",
    "Văn bản có `pham_vi_lanh_tho` = 'tinh' chỉ áp dụng trong `dia_ban_ap_dung`, "
    "không được trình bày như quy định toàn quốc.",
    "Điểm trong `diem_tac_dong_nganh` đo CƯỜNG ĐỘ QUY PHẠM hướng vào một ngành, "
    "KHÔNG đo chi phí kinh tế. Phải ghi rõ điều này khi lần đầu nhắc tới điểm số.",
]


# ──────────────────────────────────────────────
# (b) Phân tích văn bản mới
# ──────────────────────────────────────────────
def build_update_context(session, rag: RAGDatabase, doc_keys: list[str],
                         scorer_version: str) -> ctx.ReportContext:
    """Ngữ cảnh cho báo cáo (b): TOÀN BỘ nội dung của các văn bản đã biết."""
    docs = session.query(Document).filter(Document.doc_key.in_(doc_keys)).all()
    if not docs:
        return ctx.ReportContext()

    thieu_trang_thai: list[str] = []
    facts, chunks, edges = [], [], []

    for doc in docs:
        facts.append(ctx.document_facts(doc, thieu_trang_thai))
        edges.extend(ctx.graph_edges(session, doc))
        for row in rag.db.execute(
            "SELECT heading, content FROM legal_chunks WHERE doc_num = ? "
            "ORDER BY chunk_index", (doc.doc_num,)
        ).fetchall():
            chunks.append({
                "doc_num": doc.doc_num,
                "heading": row["heading"],
                "content_excerpt": (row["content"] or "")[:1500],
            })

    # Văn bản CŨ bị nhóm này sửa đổi/thay thế — để nói được "thay đổi so với cái gì".
    impacted_nums = {
        e["target_doc_num"] for e in edges
        if e["chieu"].startswith("văn bản này tác động")
        and e["relation_type"] in ("Sửa đổi, bổ sung", "Thay thế", "Bãi bỏ")
    }
    impacted = []
    for old in session.query(Document).filter(
        Document.doc_num.in_(impacted_nums or {""})
    ).all():
        impacted.append(ctx.document_facts(old, []))

    thieu_metadata = sorted(impacted_nums - {d["doc_num"] for d in impacted})

    payload = {
        "thong_tin_tra_cuu": {
            "so_van_ban_phan_tich": len(facts),
            "tong_so_doan": len(chunks),
            "tong_so_quan_he": len(edges),
        },
        "han_che_du_lieu": ctx.limitations(
            thieu_trang_thai, thieu_metadata,
            ghi_chu_thoi_gian=(
                "Danh sách văn bản là toàn bộ văn bản cần phân tích trong kỳ, "
                "không phải mẫu truy xuất."
            ),
        ),
        "danh_sach_van_ban": facts,
        "chi_tiet_dieu_khoan_chunks": chunks,
        "do_thi_quan_he_van_ban_edges": edges,
        "van_ban_bi_tac_dong": impacted,
        "diem_tac_dong_nganh": ctx.industry_impact(session, doc_keys, scorer_version),
    }
    return ctx.ReportContext(payload=payload, doc_nums=[d["doc_num"] for d in facts])


def generate_update_report(session, rag: RAGDatabase, doc_keys: list[str],
                           scorer_version: str, model: str = "") -> ReportResult:
    report_ctx = build_update_context(session, rag, doc_keys, scorer_version)
    if report_ctx.is_empty():
        raise LLMUnavailable("Không có văn bản nào để phân tích.")

    today = datetime.date.today()
    header = {
        "LOAI_BAO_CAO": "cap_nhat_van_ban",
        "KY_BAO_CAO": today.strftime("%m/%Y"),
        "MOC_CAT": today.strftime("%d/%m/%Y"),
        "DOI_TUONG": DEFAULT_AUDIENCE,
    }
    result = call_report_llm(
        load_prompt("b"),
        _user_message(header, report_ctx.payload, COMMON_NOTES),
        model=model,
    )

    return ReportResult(
        kind="b", markdown=result.text, payload=report_ctx.payload,
        sidecar=_update_sidecar(report_ctx),
        truncated=result.truncated, model=result.model,
    )


def _update_sidecar(report_ctx: ctx.ReportContext) -> dict[str, Any]:
    """Bản máy đọc được của báo cáo (b) — hợp đồng để (c) tiêu thụ.

    Không bắt (c) parse markdown: markdown do mô hình sinh, cấu trúc không bảo
    đảm, và parse nó là mời lỗi vào giữa dây chuyền.
    """
    impacts = report_ctx.payload.get("diem_tac_dong_nganh", [])
    by_industry: dict[str, dict] = {}
    for row in impacts:
        code = row["ma_nganh"]
        keep = by_industry.get(code)
        if keep is None or row["cuong_do_tac_dong"] > keep["cuong_do_tac_dong"]:
            by_industry[code] = row

    affected = sorted(
        (r for r in by_industry.values()
         if r["cuong_do_tac_dong"] >= C_THRESHOLD
         and r["ty_trong_tac_dong"] >= C_MIN_SHARE),
        key=lambda r: -r["cuong_do_tac_dong"],
    )
    return {
        "doc_nums": report_ctx.doc_nums,
        "industries_affected": affected,
        "nguong_cuong_do": C_THRESHOLD,
        "nguong_ty_trong": round(C_MIN_SHARE, 2),
    }


# ──────────────────────────────────────────────
# (c) Doanh nghiệp trong ngành bị ảnh hưởng
# ──────────────────────────────────────────────
def generate_business_report(session, rag: RAGDatabase, vsic_code: str,
                             parent_markdown: str, parent_sidecar: dict[str, Any],
                             scorer_version: str, embedder=None,
                             model: str = "") -> ReportResult:
    """Báo cáo chuyên sâu cho một ngành, dựa trên kết quả báo cáo (b)."""
    industry = official_name(vsic_code) or vsic_code
    short = _short_name(vsic_code)

    # Kho quy định ngành đang chịu TRƯỚC văn bản mới — thứ cho phép nói được
    # "nghĩa vụ mới chồng lên nghĩa vụ cũ nào", điều (b) không làm được.
    existing = industry_search(rag, industry=short, limit=40, embedder=embedder)
    kept = validate_results(rag, [
        {"id": r.id, "doc_num": r.doc_num, "heading": r.heading, "content": r.content}
        for r in existing
    ])

    doc_keys = [
        d.doc_key for d in session.query(Document).filter(
            Document.doc_num.in_(parent_sidecar.get("doc_nums") or [""])
        ).all()
    ]
    thieu: list[str] = []
    facts = [
        ctx.document_facts(d, thieu)
        for d in session.query(Document).filter(Document.doc_key.in_(doc_keys)).all()
    ]

    payload = {
        "bao_cao_goc": parent_markdown,
        "thong_tin_tra_cuu": {
            "nganh": industry,
            "ma_nganh": vsic_code,
            "so_van_ban_moi": len(facts),
            "so_dieu_khoan_hien_huu": len(kept),
        },
        "han_che_du_lieu": ctx.limitations(
            thieu, [], loai_do_het_hieu_luc=len(existing) - len(kept),
            ghi_chu_thoi_gian=(
                "Kho quy định hiện hữu là kết quả truy xuất theo ngành, đã loại "
                "văn bản hết hiệu lực toàn bộ."
            ),
        ),
        "danh_sach_van_ban": facts,
        "quy_dinh_hien_huu_cua_nganh": [{
            "doc_num": c["doc_num"], "heading": c["heading"],
            "content_excerpt": (c["content"] or "")[:1200],
            **({"canh_bao_hieu_luc": c["canh_bao_hieu_luc"]}
               if c.get("canh_bao_hieu_luc") else {}),
        } for c in kept[:30]],
        "diem_tac_dong_nganh": [
            r for r in parent_sidecar.get("industries_affected", [])
            if r["ma_nganh"] == vsic_code
        ],
    }

    today = datetime.date.today()
    header = {
        "LOAI_BAO_CAO": "tac_dong_nganh",
        "NGANH": f"{industry} (VSIC cấp 1, mã {vsic_code})",
        "KY_BAO_CAO": today.strftime("%m/%Y"),
        "MOC_CAT": today.strftime("%d/%m/%Y"),
        "DOI_TUONG": DEFAULT_AUDIENCE,
    }
    notes = COMMON_NOTES + [
        "TUYỆT ĐỐI không đưa ra kết luận mâu thuẫn với `bao_cao_goc`. Hai tài "
        "liệu này tới tay cùng một người trong cùng một ngày.",
    ]
    result = call_report_llm(load_prompt("c"), _user_message(header, payload, notes),
                             model=model)

    return ReportResult(kind="c", markdown=result.text, payload=payload,
                        truncated=result.truncated, model=result.model)


def _short_name(vsic_code: str) -> str:
    from src.obsidian.vsic import BY_CODE

    return BY_CODE.get(vsic_code, {}).get("ten_ngan", vsic_code)


__all__ = [
    "C_MIN_SHARE", "C_THRESHOLD", "ReportResult", "build_update_context",
    "generate_business_report", "generate_update_report", "code_of",
]
