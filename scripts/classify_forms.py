"""
Chạy phễu ba tầng trên các biểu mẫu đã cào: quyết định mẫu nào phục vụ kinh doanh.

    python -m scripts.classify_forms --khong-mo-hinh    # chỉ hai tầng quy tắc, miễn phí
    python -m scripts.classify_forms                    # đủ ba tầng
    python -m scripts.classify_forms --limit 200        # hiệu chuẩn trên một mẫu nhỏ
    python -m scripts.classify_forms --chay-lai         # phân loại lại từ đầu

Chạy SAU `crawl_forms` và TRƯỚC `build_forms`: dựng DOCX + PDF cho cả kho rồi mới
biết phần lớn là báo cáo nội bộ của cơ quan nhà nước thì đã đốt công vô ích.

Mỗi mẫu chỉ tốn một lượt gọi mô hình DUY NHẤT trong cả đời nó — kết quả bám theo
`body_hash`, chỉ phân loại lại khi ruột mẫu đổi.
"""
from __future__ import annotations

import argparse
import logging

from src.forms import search
from src.forms.pheu import chay_pheu
from src.storage.database import SessionLocal, init_db

logger = logging.getLogger(__name__)


def main() -> None:
    ap = argparse.ArgumentParser(description="Phân loại biểu mẫu doanh nghiệp")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--chay-lai", action="store_true",
                    help="Phân loại lại cả mẫu đã có nhãn")
    ap.add_argument("--khong-mo-hinh", action="store_true",
                    help="Chỉ chạy hai tầng quy tắc, không gọi LLM")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    init_db()

    session = SessionLocal()
    try:
        tk = chay_pheu(
            session,
            gioi_han=args.limit,
            chay_lai=args.chay_lai,
            dung_mo_hinh=not args.khong_mo_hinh,
        )
        print(f"\nPhễu: {tk.tom_tat()}")

        n = search.dung_lai_chi_muc(session)
        print(f"Chỉ mục tìm kiếm: {n} biểu mẫu doanh nghiệp.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
