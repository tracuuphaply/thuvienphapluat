"""
Sinh báo cáo pháp lý PDF cho từng ngành, để gửi cho doanh nghiệp.

Mỗi báo cáo phải qua bước đối chiếu số hiệu văn bản với kho trước khi xuất PDF.
Tài liệu gửi ra ngoài mà trích dẫn một văn bản không tồn tại thì hỏng uy tín,
nên mặc định báo cáo có số hiệu lạ sẽ KHÔNG được xuất — dùng --allow-unverified
nếu muốn xuất kèm cảnh báo để tự rà tay.

Thương hiệu đọc từ report_branding.json ở thư mục gốc (xem report_branding.example.json).

Chạy:
    python -m scripts.generate_industry_reports --dry-run
    python -m scripts.generate_industry_reports
    python -m scripts.generate_industry_reports --industries "Y tế & Dược phẩm"
"""
import argparse
import collections
import datetime
import json
import logging
import re
import sys
import time
from datetime import date
from pathlib import Path

from src.config import DATA_DIR, PROJECT_ROOT
from src.obsidian.config_obsidian import INDUSTRY_MAP
from src.rag.citation_check import check_citations
from src.rag.db_rag import RAGDatabase
from src.rag.report_generator import generate_compliance_report
from src.utils.report_pdf import ReportMeta, build_report_pdf
from src.utils.report_theme import (
    Figure, bar_counts, bar_status, timeline_effective_dates,
)

logger = logging.getLogger(__name__)

BRANDING_PATH = PROJECT_ROOT / "report_branding.json"
OUTPUT_DIR = DATA_DIR / "reports" / "nganh"

# Bản tin gửi chủ doanh nghiệp: ngắn, đầy bảng biểu và mốc thời gian. Bản 8–15
# trang gần như không ai đọc hết khi nhận qua email.
DEFAULT_LENGTH = "Báo cáo súc tích 4–6 trang A4, ưu tiên bảng biểu và mốc thời gian"


def load_branding() -> dict:
    if not BRANDING_PATH.exists():
        logger.warning("Chưa có %s — dùng chân trang trung tính", BRANDING_PATH.name)
        return {}
    try:
        return json.loads(BRANDING_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Không đọc được %s: %s", BRANDING_PATH.name, e)
        return {}


def slugify(name: str) -> str:
    """Tên file an toàn, giữ chữ tiếng Việt có dấu."""
    s = re.sub(r"[\\/:*?\"<>|]+", "-", name)
    return re.sub(r"\s+", "_", s.strip())


def industry_documents(industry: str) -> list[dict]:
    """Toàn bộ văn bản của ngành trong kho, không chỉ những bản được trích dẫn.

    Biểu đồ mang nhãn "toàn ngành" thì phải đếm toàn ngành. Dựng từ ~10 văn bản
    lọt vào phần trích dẫn rồi ghi là cơ cấu ngành là nói quá phạm vi dữ liệu —
    điều không chấp nhận được với tài liệu gửi cho doanh nghiệp.
    """
    rag = RAGDatabase()
    try:
        rows = rag.db.execute(
            "SELECT DISTINCT doc_num FROM legal_chunks "
            "WHERE industries LIKE ? AND doc_num IS NOT NULL",
            (f"%{industry}%",),
        ).fetchall()
    finally:
        rag.close()
    doc_nums = [r["doc_num"] for r in rows]
    if not doc_nums:
        return []

    from src.storage.database import get_session
    from src.storage.models import Document

    with get_session() as session:
        docs = session.query(Document).filter(Document.doc_num.in_(doc_nums)).all()
        return [
            {
                "doc_type": d.doc_type or "Chưa phân loại",
                "eff_status": d.eff_status or "Chưa xác định",
                "eff_from": str(d.eff_from) if d.eff_from else "",
            }
            for d in docs
        ]


def build_figures(industry: str, ctx: dict) -> list[Figure]:
    """Biểu đồ thống kê toàn ngành, lấy thẳng từ kho."""
    docs = industry_documents(industry)
    if not docs:
        # Không có thống kê ngành thì lùi về bộ văn bản đã trích dẫn, và nói rõ
        # phạm vi trong tiêu đề.
        docs = ctx.get("danh_sach_van_ban") or []
        scope_note = "trong phạm vi rà soát của báo cáo"
    else:
        scope_note = "trong cơ sở dữ liệu"
    if not docs:
        return []

    figures: list[Figure] = []
    total = len(docs)

    by_type = collections.Counter(d.get("doc_type") or "Chưa phân loại" for d in docs)
    top = by_type.most_common(7)
    figures.append(Figure(
        len(figures) + 1,
        f"Cơ cấu văn bản điều chỉnh ngành theo loại ({total} văn bản {scope_note})",
        bar_counts([k for k, _ in top], [v for _, v in top]),
    ))

    by_status = collections.Counter(d.get("eff_status") or "Chưa xác định" for d in docs)
    figures.append(Figure(
        len(figures) + 1,
        "Tình trạng hiệu lực của văn bản trong ngành",
        bar_status(dict(by_status)),
    ))

    # Mốc hiệu lực từ hôm nay trở đi — phần có giá trị hành động nhất.
    today = date.today()
    upcoming: collections.Counter = collections.Counter()
    for d in docs:
        try:
            eff = date.fromisoformat((d.get("eff_from") or "")[:10])
        except ValueError:
            continue
        if eff >= today:
            upcoming[f"{eff.month:02d}/{str(eff.year)[2:]}"] += 1
    # Một hai mốc lẻ vẽ ra cột chiếm trọn khung, trông như lỗi in. Biểu đồ chỉ có
    # nghĩa khi có đủ mốc để thấy được phân bố theo thời gian.
    if len(upcoming) >= 3 and sum(upcoming.values()) >= 4:
        months = sorted(upcoming, key=lambda m: (m[3:], m[:2]))[:8]
        figures.append(Figure(
            len(figures) + 1,
            "Mốc có hiệu lực sắp tới — doanh nghiệp cần chuẩn bị",
            timeline_effective_dates(months, [upcoming[m] for m in months]),
        ))
    elif upcoming:
        logger.info(
            "Bỏ biểu đồ mốc hiệu lực: chỉ có %d mốc, quá thưa để vẽ",
            sum(upcoming.values()),
        )
    return figures


def build_one(db: RAGDatabase, industry: str, brand: dict, days: int,
              allow_unverified: bool) -> dict:
    result: dict = {"nganh": industry}
    t0 = time.time()

    ctx: dict = {}
    md = generate_compliance_report(
        db, industry=industry, days=days, desired_length=DEFAULT_LENGTH,
        context_sink=ctx,
    )
    result["ky_tu"] = len(md)

    if "KHÔNG ĐỦ DỮ LIỆU" in md:
        result["trang_thai"] = "khong_du_du_lieu"
        return result

    check = check_citations(md)
    result["trich_dan"] = check.total
    result["trich_dan_la"] = len(check.missing)
    if not check.ok:
        logger.warning("%s — %s", industry, check.summary())
        if not allow_unverified:
            result["trang_thai"] = "chan_vi_trich_dan_la"
            result["chi_tiet"] = check.missing
            return result
        md += (
            "\n\n> ⚠️ **Cần rà soát**: các số hiệu sau không đối chiếu được với "
            "cơ sở dữ liệu — " + ", ".join(check.missing) + "\n"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"Bao_cao_phap_ly_{slugify(industry)}.pdf"

    footer_bits = [brand.get(k) for k in ("company", "email", "phone", "website")]
    end = date.today()
    start = end - datetime.timedelta(days=days)
    from src.obsidian.config_obsidian import code_of, official_name
    meta = ReportMeta(
        industry=industry,
        industry_code=code_of(industry),
        industry_official=official_name(industry),
        period=f"Tháng {start:%m/%Y} – {end:%m/%Y}",
        cutoff=f"{end:%d/%m/%Y}",
        scope=brand.get("scope", ""),
        company=brand.get("company", ""),
        contact=brand.get("footer") or " · ".join(b for b in footer_bits if b),
        figures=build_figures(industry, ctx),
    )
    result["so_bieu_do"] = len(meta.figures)
    build_report_pdf(md, out, meta)

    # Lưu cả bản Markdown để sửa tay khi cần
    out.with_suffix(".md").write_text(md, encoding="utf-8")

    result.update(
        trang_thai="ok",
        file=str(out),
        giay=round(time.time() - t0),
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--industries", nargs="*", help="mặc định: tất cả 10 ngành")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--dry-run", action="store_true", help="chỉ liệt kê, không gọi API")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="vẫn xuất PDF khi có số hiệu không đối chiếu được")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    brand = load_branding()
    targets = args.industries or list(INDUSTRY_MAP)

    print(f"Sẽ sinh {len(targets)} báo cáo, độ dài: {DEFAULT_LENGTH}")
    if brand.get("company"):
        print(f"Thương hiệu: {brand['company']}")
    else:
        print("Thương hiệu: (chưa cấu hình — chân trang trung tính)")
    for t in targets:
        print(f"    - {t}")
    if args.dry_run:
        return 0

    db = RAGDatabase()
    rows = []
    try:
        for idx, industry in enumerate(targets, 1):
            logger.info("[%d/%d] %s", idx, len(targets), industry)
            try:
                rows.append(build_one(db, industry, brand, args.days,
                                      args.allow_unverified))
            except Exception as e:
                logger.error("  lỗi: %s: %s", type(e).__name__, e)
                rows.append({"nganh": industry, "trang_thai": "loi", "chi_tiet": str(e)})
    finally:
        db.close()

    print("\n=== KẾT QUẢ ===")
    print(f"{'NGÀNH':<28}{'TRẠNG THÁI':<22}{'TRÍCH DẪN':>10}{'KÝ TỰ':>8}")
    print("-" * 70)
    for r in rows:
        td = f"{r.get('trich_dan', 0) - r.get('trich_dan_la', 0)}/{r.get('trich_dan', 0)}"
        print(f"{r['nganh']:<28}{r['trang_thai']:<22}{td:>10}{r.get('ky_tu', 0):>8}")
    ok = sum(1 for r in rows if r["trang_thai"] == "ok")
    print(f"\nXuất được {ok}/{len(rows)} PDF → {OUTPUT_DIR}")

    for r in rows:
        if r["trang_thai"] == "chan_vi_trich_dan_la":
            print(f"  ⚠ {r['nganh']}: số hiệu không đối chiếu được — {r['chi_tiet']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
