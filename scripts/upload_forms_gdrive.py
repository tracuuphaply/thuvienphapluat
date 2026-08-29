"""
Tải bản .docx của biểu mẫu lên Google Drive và ghi liên kết vào kho.

    python -m scripts.upload_forms_gdrive --dry-run
    python -m scripts.upload_forms_gdrive --limit 5
    python -m scripts.upload_forms_gdrive

VÌ SAO PHẢI LÀ DRIVE. Trang công khai vốn trỏ người dùng về Thư viện Pháp luật để
lấy bản gốc — nghĩa là đẩy họ ra khỏi kho của mình, tới một trang có tường
Cloudflare và có thể đổi hoặc gỡ mẫu bất cứ lúc nào. Bản .docx do mình dựng lại
thì nằm trên đĩa máy chạy, không ai ngoài mở được. Drive là chỗ duy nhất vừa của
mình vừa mở được bằng một đường link.

CHỈ .docx, KHÔNG .pdf. Bản Word là bản ĐIỀN ĐƯỢC — thứ người ta thật sự cần ở một
biểu mẫu; bản PDF chỉ để in và vẫn tải được từ trang công khai. Đo trên 653 mẫu:
docx 24 MB, pdf 74 MB. Tải cả hai là gấp bốn dung lượng để thêm một thứ đã có
đường lấy khác.

CHẠY LẠI ĐƯỢC. Mẫu nào đã có `gdrive_docx_link` thì bỏ qua, nên đứt mạng giữa
chừng chỉ cần chạy lại. Ghi kho theo từng lô 20 mẫu chứ không đợi hết: 653 lượt
tải mà mất điện ở lượt 600 thì không được phép mất cả 600.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import date
from pathlib import Path

from src.forms.store import loc_dang_cong_khai
from src.storage.database import get_session, init_db
from src.storage.models import LegalForm

logger = logging.getLogger(__name__)

# Quy tắc dựng URL công khai nằm ở src/storage/gdrive.py::lien_ket_cong_khai —
# MỘT chỗ cho cả văn bản lẫn biểu mẫu, vì cùng một cái bẫy `ouid`.
#: Thư mục Drive theo đối tượng phục vụ. Mẫu phục vụ CẢ HAI xếp vào thư mục
#: doanh nghiệp — 231 mẫu như vậy — để 638 mẫu đã tải trước đây không phải dời
#: chỗ: dời file trên Drive là đổi thứ người dùng đã có link.
TEN_THU_MUC = "Biểu mẫu doanh nghiệp"
TEN_THU_MUC_CA_NHAN = "Biểu mẫu cá nhân"
CO_LO = 20

#: Nghỉ giữa hai lượt tải. Drive có hạn mức ghi theo phút cho mỗi người dùng, và
#: `_retry_api_call` chỉ thử lại 5 lần — hết 5 lần trong lúc còn đang bị chặn thì
#: lượt nào cũng hỏng. Đo trong lần chạy đầu: 256 lượt đầu trót lọt, rồi 394 lượt
#: sau hỏng LIÊN TIẾP, tức đã đụng trần chứ không phải lỗi rải rác.
NGHI_GIAY = 0.35

#: Hỏng liên tiếp bao nhiêu lượt thì DỪNG. Lần chạy đầu không có chốt này nên nó
#: đi hết 394 mẫu còn lại chỉ để ghi 394 dòng lỗi giống hệt nhau — mất mười lăm
#: phút và không thu được gì. Hỏng hàng loạt là tín hiệu hệ thống, không phải
#: chuyện của từng file, và phải dừng để người chạy xử lý.
TRAN_HONG_LIEN_TIEP = 12


def _ten_file(form: LegalForm) -> str:
    """Tên hiển thị trên Drive: số hiệu mẫu + tiêu đề cắt ngắn.

    Tên máy (`hopdong-101.docx`) đúng cho hệ thống nhưng vô nghĩa với người mở
    thư mục Drive. Ở đó thứ duy nhất họ có là cái tên.
    """
    tieu_de = (form.title or form.form_key).strip()
    tieu_de = " ".join(tieu_de.split())[:90]
    an = "".join(c for c in tieu_de if c not in '\\/:*?"<>|')
    return f"{form.form_key} — {an}.docx".strip()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Đếm và in mẫu, không tải")
    ap.add_argument("--limit", type=int, help="Chỉ xử lý N mẫu đầu")
    ap.add_argument("--lai", action="store_true",
                    help="Tải lại cả mẫu đã có liên kết Drive")
    args = ap.parse_args()

    from src.storage import gdrive

    init_db()
    with get_session() as session:
        # Tải cho MỌI mẫu sẽ lên trang công khai — doanh nghiệp HOẶC cá nhân.
        #
        # Chỗ này từng lọc `is_business.is_(True)`: cổng THỨ TÁM chặn đối tượng
        # cá nhân, sau `build_forms`. Kế hoạch mở kho liệt kê sáu chỗ; thực tế có
        # tám. Bỏ sót chỗ này thì mẫu cá nhân dựng xong vẫn nằm trên đĩa máy
        # chạy, không ai ngoài mở được — mà trang công khai lại trỏ về Drive.
        q = loc_dang_cong_khai(
            session.query(LegalForm).filter(LegalForm.docx_path.isnot(None))
        ).order_by(LegalForm.form_key)
        if not args.lai:
            q = q.filter(LegalForm.gdrive_docx_link.is_(None))
        forms = q.all()
        if args.limit:
            forms = forms[: args.limit]

        thieu = [f for f in forms if not Path(f.docx_path).exists()]
        forms = [f for f in forms if Path(f.docx_path).exists()]
        tong_mb = sum(Path(f.docx_path).stat().st_size for f in forms) / 1024 / 1024

        print(f"=== Sẽ tải {len(forms)} bản .docx ({tong_mb:.1f} MB) ===")
        if thieu:
            print(f"  BỎ QUA {len(thieu)} mẫu thiếu file trên đĩa")
        for f in forms[:3]:
            print(f"  {f.form_key:16} → {_ten_file(f)}")

        if args.dry_run or not forms:
            session.rollback()
            return

        thu_muc = gdrive.ensure_root_folder()
        if not thu_muc:
            print("KHÔNG lấy được thư mục gốc Drive — kiểm tra GDRIVE_ROOT_FOLDER_ID "
                  "và credentials/gdrive_token.json")
            return
        thu_muc_bm = gdrive.ensure_folder(thu_muc, TEN_THU_MUC)
        thu_muc_cn = gdrive.ensure_folder(thu_muc, TEN_THU_MUC_CA_NHAN)
        if not thu_muc_bm or not thu_muc_cn:
            print("KHÔNG tạo được thư mục con trên Drive")
            return
        print(f"  thư mục đích: {TEN_THU_MUC} ({thu_muc_bm})")
        print(f"                {TEN_THU_MUC_CA_NHAN} ({thu_muc_cn})")

        def _thu_muc_cho(form: LegalForm) -> str:
            """Mẫu phục vụ cả hai xếp theo doanh nghiệp — xem TEN_THU_MUC."""
            return thu_muc_bm if form.is_business else thu_muc_cn

        xong = hong = lien_tiep = 0
        dung_som = False
        for i, f in enumerate(forms, 1):
            dich = _thu_muc_cho(f)
            kq = gdrive.upload_file(f.docx_path, dich, _ten_file(f))
            if kq and kq.get("id"):
                f.gdrive_docx_link = kq["link"]
                f.gdrive_folder_id = dich
                f.gdrive_uploaded_at = date.today()
                # Trang công khai phải dựng lại: liên kết tải về đổi chỗ.
                f.published_hash = None
                xong += 1
                lien_tiep = 0
            else:
                hong += 1
                lien_tiep += 1
                logger.warning("Tải hỏng: %s", f.form_key)
                if lien_tiep >= TRAN_HONG_LIEN_TIEP:
                    session.commit()
                    print(f"\nDỪNG SỚM: {lien_tiep} lượt hỏng liên tiếp — nhiều khả "
                          f"năng đã đụng hạn mức ghi của Drive. Chờ vài phút rồi "
                          f"chạy lại; mẫu đã tải sẽ được bỏ qua.")
                    dung_som = True
                    break
            if i % CO_LO == 0:
                session.commit()
                print(f"  {i}/{len(forms)} · xong {xong} · hỏng {hong}")
            time.sleep(NGHI_GIAY)
        session.commit()

    print("\n=== Kết quả ===")
    print(f"  đã tải       {xong}")
    print(f"  hỏng         {hong}")
    print(f"  thiếu file   {len(thieu)}")
    if dung_som:
        print("  DỪNG SỚM vì hỏng liên tiếp — chạy lại lệnh này để tiếp tục.")
    print("\nDựng lại trang công khai để liên kết trỏ về Drive:")
    print("  python -m scripts.publish_site --out ~/Downloads/legal-vault-public/content")


if __name__ == "__main__":
    main()
