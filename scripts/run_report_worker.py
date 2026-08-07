"""
Rút hàng đợi sinh báo cáo.

    python -m scripts.run_report_worker --status      # xem hàng đợi
    python -m scripts.run_report_worker --max 1       # chạy thử một job
    python -m scripts.run_report_worker               # theo MAX_REPORTS_PER_DAY

Chạy TÁCH KHỎI `src.main`: gọi mô hình mất tới 300 giây, và trước đây lời gọi đó
nằm trong khối try bao trọn pipeline nên một lỗi LLM đánh dấu cả lần cào là
FAILED, kéo theo run_daily.sh bỏ luôn đồng bộ vault và RAG.

Dùng cùng khoá chống chạy chồng như pipeline, file khoá riêng.
"""
from __future__ import annotations

import argparse
import fcntl
import logging
import sys

from sqlalchemy import text

from src.config import DATA_DIR, MAX_REPORTS_PER_DAY
from src.rag.db_rag import RAGDatabase
from src.rag.reports import worker
from src.storage.database import get_session, init_db

logger = logging.getLogger(__name__)
LOCK_PATH = DATA_DIR / "report_worker.lock"


def show_status() -> None:
    with get_session() as session:
        rows = session.execute(text("""
            SELECT kind, status, COUNT(*) n FROM report_jobs
            GROUP BY kind, status ORDER BY kind, status
        """)).mappings().all()
        print("=== Hàng đợi báo cáo ===")
        if not rows:
            print("  (trống)")
        for r in rows:
            print(f"  loại {r['kind']}  {r['status']:<18} {r['n']:>4}")

        cho = session.execute(text("""
            SELECT id, kind, COALESCE(industry,'') ten, trigger_reason, scheduled_for
            FROM report_jobs WHERE status='QUEUED'
            ORDER BY priority DESC, id LIMIT 10
        """)).mappings().all()
        if cho:
            print("\n  Chờ chạy (ưu tiên cao nhất trước):")
            for r in cho:
                print(f"    #{r['id']:<5} {r['kind']}  {r['ten']:<34} "
                      f"{r['trigger_reason']:<28} {r['scheduled_for']}")

        chan = session.execute(text("""
            SELECT id, kind, citation_missing, substr(error,1,70) e
            FROM report_jobs WHERE status='BLOCKED_CITATION' LIMIT 5
        """)).mappings().all()
        if chan:
            print("\n  Bị chặn vì trích dẫn lạ:")
            for r in chan:
                print(f"    #{r['id']:<5} {r['kind']}  thiếu {r['citation_missing']} số hiệu: {r['e']}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true", help="Chỉ xem hàng đợi")
    ap.add_argument("--max", type=int, default=0, help="Số job tối đa lần này")
    args = ap.parse_args()

    init_db()
    if args.status:
        show_status()
        return

    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"Một tiến trình khác đang giữ {LOCK_PATH}. Bỏ qua lần chạy này.")
        sys.exit(0)

    from scripts.compute_impact import version_tag

    rag = RAGDatabase()
    try:
        with get_session() as session:
            stats = worker.drain(
                session, rag, version_tag(),
                max_jobs=args.max or MAX_REPORTS_PER_DAY,
            )
    finally:
        rag.close()
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()

    print("\n=== Kết quả ===")
    for k, v in stats.as_dict().items():
        print(f"  {k:10} {v}")


if __name__ == "__main__":
    main()
