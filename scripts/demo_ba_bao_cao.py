"""
Sinh một bản demo cho mỗi loại báo cáo, từ kho hiện tại.

Khác với worker: chạy thẳng, không qua hàng đợi, không cần bật lịch tự động.
Dùng để xem ba loại báo cáo trông ra sao trên dữ liệu thật trước khi quyết định
có bật hệ thống tự động hay không.

    python -m scripts.demo_ba_bao_cao --loai a b c
    python -m scripts.demo_ba_bao_cao --loai b --doc-num 301/2026/NĐ-CP

Báo cáo (c) tiêu thụ đầu ra của (b) nên nếu chạy cả hai thì (b) phải chạy
trước — script tự lo thứ tự đó.

Mọi báo cáo đều đi qua check_citations: số hiệu không có trong kho là lỗi cứng,
không phải cảnh báo. Bản bị chặn vẫn được ghi ra đĩa kèm hậu tố _BI_CHAN để xem
được mô hình đã bịa gì.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import text

from src.config import DATA_DIR
from src.rag.citation_check import check_citations
from src.rag.db_rag import RAGDatabase
from src.rag.reports import generators
from src.rag.reports.llm import LLMUnavailable
from src.storage.database import get_session
from src.storage.models import Document

logger = logging.getLogger(__name__)

OUT_DIR = DATA_DIR / "reports" / "demo"

# Ngành mặc định cho (a) và (c). K là nhóm có nhiều văn bản nhất trong kho nên
# demo có dữ liệu thật để nói, không phải một bản rỗng.
NGANH_MAC_DINH = "K"


TIEU_DE = {
    "a": "Báo cáo tổng hợp pháp lý ngành",
    "b": "Báo cáo cập nhật văn bản mới",
    "c": "Báo cáo chuyên sâu cho doanh nghiệp",
}


def _branding() -> dict:
    from src.config import PROJECT_ROOT

    path = PROJECT_ROOT / "report_branding.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _xuat_pdf(md_text: str, ten: str, loai: str, nhan: str) -> Path | None:
    """Dựng PDF có bìa thương hiệu từ markdown.

    Cùng bộ dựng với scripts/generate_industry_reports.py — không tự chế bản
    thứ hai, vì quy ước markdown ở mục 7 của prompt được viết cho đúng bộ này.
    """
    import datetime

    from src.utils.report_pdf import ReportMeta, build_report_pdf

    brand = _branding()
    hom_nay = datetime.date.today()
    meta = ReportMeta(
        industry=nhan,
        period=f"{TIEU_DE[loai]} · {hom_nay:%m/%Y}",
        cutoff=f"{hom_nay:%d/%m/%Y}",
        scope=brand.get("scope", ""),
        company=brand.get("company", ""),
        contact=brand.get("footer", ""),
    )
    try:
        return build_report_pdf(md_text, OUT_DIR / f"{ten}.pdf", meta)
    except Exception as e:
        # Không nuốt: thiếu font là lỗi hay gặp nhất khi đổi máy, và nếu im
        # lặng thì người dùng chỉ thấy "không có file PDF" mà không biết vì sao.
        print(f"    ✗ không dựng được PDF: {type(e).__name__}: {e}")
        return None


def _ghi(ten: str, loai: str, nhan: str, result,
         sidecar: dict | None = None) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    kiem = check_citations(
        result.markdown, extra_allowed=getattr(result, "allowed_doc_nums", None))
    hau_to = "" if kiem.ok else "_BI_CHAN"

    md = OUT_DIR / f"{ten}{hau_to}.md"
    md.write_text(result.markdown, encoding="utf-8")
    if sidecar is not None:
        (OUT_DIR / f"{ten}.json").write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n  → {md}")
    print(f"    {len(result.markdown):,} ký tự | model {result.model}"
          + (" | BỊ CẮT" if result.truncated else ""))
    if kiem.ok:
        print(f"    trích dẫn: {kiem.total} số hiệu, tất cả có trong kho")
    else:
        # Bản bịa số hiệu KHÔNG được dựng thành PDF: PDF là dạng gửi cho khách,
        # còn markdown là bản để soi lỗi.
        print(f"    ✗ CHẶN: {len(kiem.missing)} số hiệu không có trong kho — "
              f"{kiem.missing[:5]}")
        print("    (không xuất PDF cho bản bị chặn)")
        return md

    pdf = _xuat_pdf(result.markdown, f"{ten}{hau_to}", loai, nhan)
    if pdf:
        print(f"    → {pdf}  ({pdf.stat().st_size / 1024:.0f} KB)")
    return md


def demo_a(session, rag, version: str, nganh: str) -> None:
    """(a) Tổng hợp pháp lý một ngành.

    Dùng ĐÚNG bộ sinh của worker (generators.generate_industry_report), không
    dùng report_generator.generate_compliance_report cũ nữa: đường theo lịch
    (enqueue_quarterly_reports → worker) chạy bộ mới, nên demo phải khớp — nhất
    là để thấy bước ĐỌC insight từng văn bản, thứ bản cũ không có.
    """
    from src.obsidian.vsic import VSIC_LEVEL1

    ten_ngan = next((n["ten_ngan"] for n in VSIC_LEVEL1 if n["ma"] == nganh), None)
    if not ten_ngan:
        print(f"\n  ✗ (a) mã ngành {nganh!r} không có trong VSIC cấp 1.")
        return

    print(f"\n=== (a) Tổng hợp ngành — {nganh} · {ten_ngan} ===")
    result = generators.generate_industry_report(session, rag, nganh, version)
    _ghi("a_tong_hop_nganh", "a", f"{nganh} · {ten_ngan}", result)


def demo_b(session, rag, version: str, doc_num: str | None) -> tuple[Path, dict] | None:
    """(b) Phân tích văn bản mới ban hành."""
    q = session.query(Document).filter(
        Document.is_closure_node == False,  # noqa: E712
        Document.has_chunks == True,  # noqa: E712
    )
    if doc_num:
        docs = q.filter(Document.doc_num == doc_num).all()
    else:
        # Ưu tiên văn bản CÓ sửa đổi/thay thế văn bản khác — đó là ca cho thấy
        # rõ nhất giá trị của bao đóng: đối chiếu quy định cũ với quy định mới.
        # Lấy rộng rồi lọc "liên quan doanh nghiệp", giữ 2 văn bản mới nhất — để
        # demo không rơi vào một quyết định y tế cấp tỉnh như trước.
        from src.legal.business_relevance import filter_business_docs

        candidates = q.filter(Document.doc_key.in_(
            session.execute(text("""
                SELECT DISTINCT s.doc_key FROM document_references r
                JOIN documents s ON s.id = r.source_doc_id
                JOIN documents t ON t.id = r.target_doc_id
                WHERE r.relation_type IN ('Sửa đổi, bổ sung','Thay thế','Bãi bỏ')
                  AND t.has_chunks = 1 AND COALESCE(s.is_closure_node,0) = 0
                ORDER BY s.issue_date DESC LIMIT 40
            """)).scalars().all()
        )).order_by(Document.issue_date.desc()).all()
        docs = filter_business_docs(candidates)[:2]

    if not docs:
        print("\n=== (b) — không tìm được văn bản liên quan doanh nghiệp, bỏ qua ===")
        return None

    print(f"\n=== (b) Văn bản mới — {', '.join(d.doc_num for d in docs)} ===")
    result = generators.generate_update_report(
        session, rag, [d.doc_key for d in docs], version)
    nhan = ", ".join(d.doc_num for d in docs)
    md = _ghi("b_van_ban_moi", "b", nhan, result, sidecar=result.sidecar)
    return md, result.sidecar


def demo_c(session, rag, version: str, parent: tuple[Path, dict], nganh: str) -> None:
    """(c) Chuyên sâu cho doanh nghiệp trong ngành bị ảnh hưởng."""
    md_path, sidecar = parent
    # Khoá là `ma_nganh`, giống worker.chain_business_reports — đừng đoán tên.
    anh_huong = sidecar.get("industries_affected") or []
    if anh_huong:
        nganh = anh_huong[0]["ma_nganh"]
        print(f"\n=== (c) Doanh nghiệp — ngành {nganh} (chọn từ sidecar của (b)) ===")
    else:
        print(f"\n=== (c) Doanh nghiệp — ngành {nganh} "
              f"((b) không chọn được ngành nào vượt ngưỡng, dùng mặc định) ===")

    result = generators.generate_business_report(
        session, rag, nganh,
        md_path.read_text(encoding="utf-8"), sidecar, version)
    from src.obsidian.vsic import VSIC_LEVEL1
    ten = next((n["ten_ngan"] for n in VSIC_LEVEL1 if n["ma"] == nganh), nganh)
    _ghi("c_doanh_nghiep", "c", f"{nganh} · {ten}", result)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loai", nargs="+", choices=["a", "b", "c"],
                    default=["a", "b", "c"])
    ap.add_argument("--doc-num", help="Chỉ định văn bản cho báo cáo (b)")
    ap.add_argument("--nganh", default=NGANH_MAC_DINH, help="Mã VSIC cấp 1")
    args = ap.parse_args()

    from src.config import impact_scorer_version

    version = impact_scorer_version()
    rag = RAGDatabase()
    try:
        with get_session() as session:
            parent = None
            if "a" in args.loai:
                try:
                    demo_a(session, rag, version, args.nganh)
                except LLMUnavailable as e:
                    print(f"\n  ✗ (a) không sinh được: {e}")

            if "b" in args.loai or "c" in args.loai:
                try:
                    parent = demo_b(session, rag, version, args.doc_num)
                except LLMUnavailable as e:
                    print(f"\n  ✗ (b) không sinh được: {e}")

            if "c" in args.loai:
                if parent is None:
                    print("\n  ✗ (c) bỏ qua: nó tiêu thụ đầu ra của (b), mà (b) "
                          "chưa có kết quả.")
                else:
                    try:
                        demo_c(session, rag, version, parent, args.nganh)
                    except LLMUnavailable as e:
                        print(f"\n  ✗ (c) không sinh được: {e}")
    finally:
        rag.close()

    print(f"\nTất cả nằm trong {OUT_DIR}")


if __name__ == "__main__":
    main()
