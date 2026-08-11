"""
Dựng lại PDF từ một báo cáo markdown đã có, để xem biểu đồ mới trông thế nào.

    python -m scripts.demo_pdf_bieu_do data/reports/nganh/job00029_2026-08-09.md

KHÔNG GỌI MÔ HÌNH. Phần chữ lấy nguyên từ file markdown đã sinh trước đó; chỉ
biểu đồ và bố cục là dựng mới. Dùng khi cần xem phần trực quan mà không phụ
thuộc nhà cung cấp LLM — hoặc khi nhà cung cấp đang chết, đúng tình huống nó ra
đời.

Số liệu vẽ biểu đồ lấy từ CHÍNH những số hiệu mà báo cáo đó trích dẫn, đúng như
worker làm: có vậy biểu đồ mới nói cùng một chuyện với phần chữ.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path

from src.config import PROJECT_ROOT
from src.rag.citation_check import extract_doc_nums
from src.rag.reports import context as ctx
from src.rag.reports import figures as figures_mod
from src.storage.database import get_session, init_db
from src.storage.models import Document
from src.utils.report_pdf import ReportMeta, build_report_pdf

logger = logging.getLogger(__name__)

LOAI_THEO_THU_MUC = {"nganh": "a", "van_ban_moi": "b", "doanh_nghiep": "c"}


def dung_payload(session, doc_nums: list[str], version: str) -> dict:
    """Dựng lại khối dữ kiện từ các số hiệu báo cáo đã trích dẫn."""
    docs = session.query(Document).filter(Document.doc_num.in_(doc_nums)).all()
    thieu: list[str] = []
    return {
        "danh_sach_van_ban": [ctx.document_facts(d, thieu) for d in docs],
        "diem_tac_dong_nganh": ctx.industry_impact(
            session, [d.doc_key for d in docs], version),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("md_path", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    md = args.md_path.read_text(encoding="utf-8")
    kind = LOAI_THEO_THU_MUC.get(args.md_path.parent.name, "a")
    # version_tag(), KHÔNG phải IMPACT_SCORER_VERSION trần. Hằng số trong config
    # là "v1.0.0" còn DB lưu "v1.0.0+text-embedding-3-small" — tên model nhúng
    # được gắn vào để điểm cũ và điểm mới không lẫn nhau. Lọc bằng hằng số trần
    # thì mọi truy vấn trả về 0 dòng và biểu đồ ngành lặng lẽ biến mất. Tôi vừa
    # mắc đúng lỗi này lúc viết script.
    from scripts.compute_impact import version_tag
    version = version_tag()

    init_db()
    with get_session() as session:
        nums = sorted(set(extract_doc_nums(md)))
        payload = dung_payload(session, nums, version)

    figs = figures_mod.build_figures(kind, payload)

    print(f"\nBáo cáo   : {args.md_path.name}  (loại {kind})")
    print(f"Số hiệu   : {len(nums)} trích dẫn → "
          f"{len(payload['danh_sach_van_ban'])} văn bản tra được trong kho")
    print(f"Biểu đồ   : {len(figs)}")
    for f in figs:
        print(f"   {f.number}. {f.title}")
    if not figs:
        print("   (không đủ dữ liệu để vẽ — xem ngưỡng trong figures.py)")

    brand_path = PROJECT_ROOT / "report_branding.json"
    brand = (json.loads(brand_path.read_text(encoding="utf-8"))
             if brand_path.exists() else {})
    hom_nay = datetime.date.today()

    meta = ReportMeta(
        figures=figs,
        industry=brand.get("demo_industry", "Bản demo — dựng lại từ báo cáo đã có"),
        period=f"Bản demo biểu đồ · {hom_nay:%m/%Y}",
        cutoff=f"{hom_nay:%d/%m/%Y}",
        scope=brand.get("scope", ""),
        company=brand.get("company", ""),
        contact=brand.get("footer", ""),
    )

    out = args.out or args.md_path.with_name(args.md_path.stem + "_DEMO.pdf")
    build_report_pdf(md, out, meta)
    print(f"\nĐã ghi: {out}")


if __name__ == "__main__":
    main()
