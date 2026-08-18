"""
Dựng lại biểu mẫu thành Markdown + DOCX + PDF của mình.

    python -m scripts.build_forms                # mọi mẫu doanh nghiệp chưa dựng
    python -m scripts.build_forms --limit 20     # thử một lô nhỏ
    python -m scripts.build_forms --dung-lai     # dựng lại cả mẫu đã có file
    python -m scripts.build_forms --khong-pdf    # nhanh gấp ~4 lần, chỉ MD + DOCX

CHỈ DỰNG MẪU `is_business = 1`. Chạy trước `classify_forms` thì không có mẫu nào
để dựng — đó là đúng, không phải lỗi.

File ra nằm ở data/forms/build/{form_key}/, TÁCH khỏi data/forms/html/ chứa bản
gốc TVPL. Hai thư mục không được lẫn: bản dựng lại thì đăng công khai được, bản
HTML gốc thì không (xem src/forms/renderer.py § ranh giới bản quyền).
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.forms.pheu import doc_ruot_mau
from src.forms.renderer import dung_tat_ca
from src.sources.tvpl_forms_parse import FormParseError, tach_chi_tiet
from src.storage.database import SessionLocal, init_db
from src.storage.models import LegalForm, LegalFormRef

logger = logging.getLogger(__name__)


def _ruot_html(form: LegalForm) -> str:
    """Ruột mẫu ở dạng HTML, đọc lại từ trang đã lưu.

    `doc_ruot_mau()` của pheu.py trả về CHỮ TRƠN — đủ cho bộ đếm từ khoá nhưng
    mất sạch bảng, mà bảng là toàn bộ nội dung của biểu mẫu.
    """
    if not form.body_html_path or not Path(form.body_html_path).exists():
        return ""
    try:
        return tach_chi_tiet(
            Path(form.body_html_path).read_text(encoding="utf-8"),
            form.source, form.external_id,
        ).body_html
    except FormParseError:
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Dựng file biểu mẫu")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dung-lai", action="store_true",
                    help="Dựng lại cả mẫu đã có file")
    ap.add_argument("--khong-pdf", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    init_db()

    session = SessionLocal()
    xong = bo_qua = hong = 0
    try:
        q = session.query(LegalForm).filter(
            LegalForm.is_business.is_(True),
            LegalForm.crawl_status == "OK",
        )
        if not args.dung_lai:
            q = q.filter(LegalForm.docx_path.is_(None))
        if args.limit:
            q = q.limit(args.limit)

        forms = q.all()
        print(f"Cần dựng {len(forms)} biểu mẫu.")

        for i, form in enumerate(forms, 1):
            body = _ruot_html(form)
            if not body:
                bo_qua += 1
                logger.warning("%s: không đọc được ruột mẫu, bỏ qua", form.form_key)
                continue

            can_cu = [
                r.doc_num for r in
                session.query(LegalFormRef).filter_by(form_key=form.form_key).all()
            ]
            kq = dung_tat_ca(
                form.form_key, form.title or form.form_key, body, form.url or "",
                can_cu=can_cu,
                cap_nhat=form.updated_on.strftime("%d/%m/%Y") if form.updated_on else "",
                lam_pdf=not args.khong_pdf,
            )
            form.body_md_path = str(kq.md_path) if kq.md_path else None
            form.docx_path = str(kq.docx_path) if kq.docx_path else None
            form.pdf_path = str(kq.pdf_path) if kq.pdf_path else None
            # File đổi thì trang công khai phải đăng lại, nếu không link tải vẫn
            # trỏ tới bản cũ.
            form.published_hash = None

            if kq.canh_bao:
                hong += 1
                logger.warning("%s: %s", form.form_key, "; ".join(kq.canh_bao))
            xong += 1
            if i % 25 == 0:
                session.commit()
                print(f"  … {i}/{len(forms)}")
        session.commit()
    finally:
        session.close()

    print(f"\nXong: dựng {xong}, bỏ qua {bo_qua} (không đọc được ruột), "
          f"{hong} mẫu có cảnh báo.")


if __name__ == "__main__":
    main()
