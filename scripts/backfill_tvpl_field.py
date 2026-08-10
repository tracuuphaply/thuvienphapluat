"""
Điền lĩnh vực theo danh mục Thư viện Pháp luật cho toàn kho.

Idempotent: chạy lại chỉ ghi đè khi kết quả đổi (ví dụ sau khi bổ sung bảng
ánh xạ), và in bảng đối chiếu để soi bằng mắt.

    python -m scripts.backfill_tvpl_field --dry-run
    python -m scripts.backfill_tvpl_field
    python -m scripts.backfill_tvpl_field --xem tu_khoa   # soi nhóm suy đoán

KHÔNG ghi đè `field_code`. Cột đó giữ mã do chính TVPL gán và là dữ kiện; kết
quả ở đây có thể đến từ suy đoán nên nằm ở `tvpl_field_code` kèm
`tvpl_field_source`.
"""
from __future__ import annotations

import argparse
import collections
import logging

from src.legal.field_mapper import NGUON_KHAC, NGUON_TU_KHOA, phan_loai
from src.legal.tvpl_fields import thu_muc
from src.storage.database import get_session, init_db
from src.storage.models import Document

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--xem", choices=["tvpl", "moj_map", "tu_khoa", "khac"],
                    help="In mẫu văn bản của một nguồn để soi bằng mắt")
    args = ap.parse_args()

    init_db()
    nguon = collections.Counter()
    linh_vuc = collections.Counter()
    mau: dict[str, list[str]] = collections.defaultdict(list)
    doi = 0

    with get_session() as session:
        docs = session.query(Document).all()
        for doc in docs:
            kq = phan_loai(doc.field_code, doc.field_name, doc.title)
            nguon[kq.nguon] += 1
            linh_vuc[kq.ma] += 1
            if len(mau[kq.nguon]) < 8:
                mau[kq.nguon].append(
                    f"{doc.doc_num:<22} → {kq.ten:<24} "
                    f"[{(doc.field_name or '—')[:28]}]"
                )
            if doc.tvpl_field_code != kq.ma or doc.tvpl_field_source != kq.nguon:
                doi += 1
                if not args.dry_run:
                    doc.tvpl_field_code = kq.ma
                    doc.tvpl_field_source = kq.nguon
        if not args.dry_run:
            session.commit()

    tong = sum(nguon.values())
    print("\n=== Nguồn phân loại ===" + ("  (DRY RUN)" if args.dry_run else ""))
    for n in ("tvpl", "moj_map", "tu_khoa", "khac"):
        s = nguon.get(n, 0)
        print(f"  {n:<10} {s:>5}  {100*s/tong:>5.1f}%")
    print(f"\n  bản ghi thay đổi: {doi}/{tong}")

    print(f"\n=== Phân bố {len(linh_vuc)}/27 lĩnh vực ===")
    for ma, s in sorted(linh_vuc.items()):
        print(f"  {thu_muc(ma):<34} {s:>5}")

    # Hai nhóm này là suy đoán, nên in mẫu để người vận hành soi được.
    for n in (args.xem,) if args.xem else (NGUON_TU_KHOA, NGUON_KHAC):
        if not mau.get(n):
            continue
        print(f"\n=== Mẫu nguồn '{n}' (suy đoán, cần soi) ===")
        for dong in mau[n]:
            print(f"  {dong}")


if __name__ == "__main__":
    main()
