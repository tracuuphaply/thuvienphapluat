"""
Xếp hàng báo cáo tổng hợp ngành (loại a) theo kỳ.

Chạy đầu mỗi quý qua launchd. Nó chỉ XẾP HÀNG, không sinh báo cáo — worker lo
việc gọi mô hình. Tách như vậy để một lỗi LLM không làm hỏng cả lần chạy theo
lịch, và để trần MAX_REPORTS_PER_DAY vẫn có tác dụng.

    python -m scripts.enqueue_quarterly_reports --dry-run
    python -m scripts.enqueue_quarterly_reports              # ngành có văn bản
    python -m scripts.enqueue_quarterly_reports --nganh K F  # chỉ định

CHỌN NGÀNH NÀO. Không xếp cả 21 ngành: ngành không có văn bản nào trong kho sẽ
cho một báo cáo rỗng, mà báo cáo rỗng vẫn tốn một lượt gọi mô hình và vẫn đến
tay người đọc. Chỉ xếp ngành có ít nhất MIN_VAN_BAN văn bản nghiệp vụ được chấm
điểm — ngưỡng thấp, cốt để loại ngành trống chứ không phải để lọc.
"""
from __future__ import annotations

import argparse
import datetime
import logging

from sqlalchemy import text

from src.obsidian.vsic import VSIC_LEVEL1
from src.rag.reports import jobs
from src.storage.database import get_session, init_db

logger = logging.getLogger(__name__)

# Dưới mức này thì báo cáo ngành không có gì để nói.
MIN_VAN_BAN = 5


def ky_bao_cao(hom_nay: datetime.date) -> str:
    """Nhãn kỳ, dùng làm khoá chống trùng.

    Chạy hai lần trong cùng một quý phải ra cùng một khoá, nếu không mỗi lần
    khởi động lại máy sau khi lỡ mốc sẽ sinh thêm một bộ báo cáo nữa.
    """
    quy = (hom_nay.month - 1) // 3 + 1
    return f"{hom_nay.year}-Q{quy}"


def nganh_co_du_lieu(session, version: str) -> dict[str, int]:
    """Mã ngành → số văn bản nghiệp vụ đứng đầu ở ngành đó."""
    rows = session.execute(text("""
        SELECT i.vsic_code AS ma, COUNT(*) AS n FROM (
            SELECT doc_key, vsic_code,
                   ROW_NUMBER() OVER (PARTITION BY doc_key
                                      ORDER BY impact_pct_doc DESC) rn
            FROM document_industry_impact WHERE scorer_version = :v
        ) i
        JOIN documents d ON d.doc_key = i.doc_key
        WHERE i.rn = 1 AND COALESCE(d.is_closure_node, 0) = 0
        GROUP BY i.vsic_code
    """), {"v": version}).mappings().all()
    return {r["ma"]: r["n"] for r in rows}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--nganh", nargs="+", help="Mã VSIC cấp 1, mặc định: mọi "
                                               "ngành có đủ văn bản")
    ap.add_argument("--min-van-ban", type=int, default=MIN_VAN_BAN)
    args = ap.parse_args()

    from src.config import impact_scorer_version

    init_db()
    version = impact_scorer_version()
    hom_nay = datetime.date.today()
    ky = ky_bao_cao(hom_nay)
    ten_theo_ma = {n["ma"]: n["ten_ngan"] for n in VSIC_LEVEL1}

    with get_session() as session:
        dem = nganh_co_du_lieu(session, version)
        if args.nganh:
            chon = [m for m in args.nganh if m in ten_theo_ma]
            bo_qua = [m for m in args.nganh if m not in ten_theo_ma]
            if bo_qua:
                print(f"  Mã không có trong VSIC cấp 1, bỏ qua: {bo_qua}")
        else:
            chon = sorted(m for m, n in dem.items() if n >= args.min_van_ban)

        print(f"\n=== Báo cáo tổng hợp ngành, kỳ {ky} ===")
        print(f"  scorer_version : {version}")
        print(f"  ngành được xếp : {len(chon)}/{len(ten_theo_ma)}")
        trong = sorted(set(ten_theo_ma) - set(chon))
        if trong:
            print(f"  bỏ qua (dưới {args.min_van_ban} văn bản): {', '.join(trong)}")

        if args.dry_run:
            for ma in chon:
                print(f"    {ma}  {ten_theo_ma[ma]:<42} {dem.get(ma, 0):>4} văn bản")
            return

        xep, da_co = 0, 0
        for ma in chon:
            job_id = jobs.enqueue(
                session, "a", f"{ma}:{ky}",
                vsic_code=ma, industry=ten_theo_ma[ma],
                trigger_reason=f"tổng hợp định kỳ {ky}",
                # Ngành nhiều văn bản lên trước: chạm trần ngày thì phần dời
                # sang mai là phần ít quan trọng hơn.
                priority=float(dem.get(ma, 0)),
            )
            if job_id:
                xep += 1
            else:
                da_co += 1
        session.commit()

    print(f"\n  đã xếp {xep} job, {da_co} job đã có từ trước (khoá kỳ {ky})")
    print("  chạy worker để sinh: python -m scripts.run_report_worker")


if __name__ == "__main__":
    main()
