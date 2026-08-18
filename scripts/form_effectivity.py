"""
Tính hiệu lực biểu mẫu từ văn bản căn cứ của nó.

    python -m scripts.form_effectivity              # tính lại toàn kho
    python -m scripts.form_effectivity --xem        # chỉ xem, không ghi
    python -m scripts.form_effectivity --canh-bao   # liệt kê mẫu không nên dùng

BIỂU MẪU KHÔNG CÓ HIỆU LỰC RIÊNG. Nó là phụ lục kèm theo một văn bản quy phạm nên
sống chết theo văn bản đó. TVPL KHÔNG công bố điều này — trang chỉ ghi "Cập nhật:
<ngày>", mà đó là ngày họ sửa trang, không phải ngày pháp lý. Đây là chỗ hệ thống
này thêm giá trị thật so với việc vào TVPL tra tay.

CHẠY LẠI SAU MỖI LẦN CÀO VĂN BẢN, không phải một lần rồi thôi: cờ hiệu lực đổi khi
văn bản căn cứ đổi. src/main.py đã gọi tự động ở bước 9 của pipeline hằng ngày; lệnh
này để chạy tay và để soi kết quả.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from src.forms.effectivity import CANH_BAO, NHAN, suy_hieu_luc, tinh_hieu_luc
from src.storage.database import SessionLocal, init_db
from src.storage.models import LegalForm

logger = logging.getLogger(__name__)


def _in_bang(dem: dict[str, int]) -> None:
    tong = sum(dem.values()) or 1
    print(f"\n{'Trạng thái':<38} {'Số mẫu':>7}  {'Tỷ lệ':>6}")
    print("─" * 55)
    for ma, nhan in NHAN.items():
        n = dem.get(ma, 0)
        if n:
            print(f"{nhan:<38} {n:>7}  {n * 100 / tong:>5.1f}%")
    print("─" * 55)
    print(f"{'Tổng':<38} {sum(dem.values()):>7}")


def _xem_truoc(session) -> dict[str, int]:
    """Tính nhưng KHÔNG ghi — để soi trước khi đụng vào dữ liệu đã đăng."""
    moc = date.today()
    dem: dict[str, int] = {}
    for form in session.query(LegalForm).filter(LegalForm.crawl_status == "OK").all():
        kq = suy_hieu_luc(session, form.form_key, moc)
        dem[kq.state] = dem.get(kq.state, 0) + 1
    return dem


def _liet_ke_canh_bao(session, gioi_han: int = 30) -> None:
    rows = (
        session.query(LegalForm)
        .filter(LegalForm.eff_state.in_(sorted(CANH_BAO)))
        .filter(LegalForm.is_business.is_(True))
        .order_by(LegalForm.eff_state, LegalForm.form_key)
        .limit(gioi_han)
        .all()
    )
    if not rows:
        print("\nKhông có biểu mẫu doanh nghiệp nào cần cảnh báo.")
        return
    print(f"\n{len(rows)} biểu mẫu doanh nghiệp KHÔNG nên điền mà chưa kiểm lại:\n")
    for f in rows:
        print(f"  [{NHAN.get(f.eff_state, '?')}] {f.form_key}")
        print(f"    {(f.title or '')[:82]}")
        if f.eff_note:
            print(f"    → {f.eff_note[:110]}")
        if f.eff_replaced_by:
            print(f"    → tìm mẫu mới ở: {', '.join(json.loads(f.eff_replaced_by))}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Hiệu lực biểu mẫu theo căn cứ")
    ap.add_argument("--xem", action="store_true",
                    help="Chỉ tính và in kết quả, không ghi vào DB")
    ap.add_argument("--canh-bao", action="store_true",
                    help="Liệt kê biểu mẫu doanh nghiệp không nên dùng")
    ap.add_argument("--chi-kinh-doanh", action="store_true",
                    help="Chỉ tính cho mẫu đã qua phễu doanh nghiệp")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init_db()

    session = SessionLocal()
    try:
        if args.canh_bao:
            _liet_ke_canh_bao(session)
            return

        if args.xem:
            print("Chỉ xem — không ghi vào DB.")
            _in_bang(_xem_truoc(session))
            session.rollback()
            return

        dem = tinh_hieu_luc(session, chi_mau_kinh_doanh=args.chi_kinh_doanh)
        _in_bang(dem)
        print("\nTrang công khai đã được đánh dấu cần đăng lại "
              "(published_hash = NULL). Chạy: python -m scripts.publish_site")
    finally:
        session.close()


if __name__ == "__main__":
    main()
