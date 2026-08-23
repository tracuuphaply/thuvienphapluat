"""Nạp kho DEMO từ `du-lieu.json` của trang công khai.

DÙNG ĐỂ LÀM GÌ. Cơ sở dữ liệu thật (`data/legal_docs.db`) không nằm trong repo —
nó bị .gitignore loại ra vì chứa toàn văn và nặng hàng trăm MB. Ai clone repo về
mà chưa có kho thì `publish_site --html` chạy đúng nhưng dựng ra một trang rỗng:
giao diện lên, danh sách trống, và trông y hệt như code hỏng.

Script này lấp đúng khoảng đó. Nó đọc `tro-ly/du-lieu.json` — bộ metadata đã
đăng công khai — rồi dựng một SQLite đủ để `publish_site --html` chạy ra trang
thật, xem được bằng mắt.

    python -m scripts.nap_demo --tu ../legal-vault-public/tro-ly/du-lieu.json
    python -m scripts.nap_demo --tu du-lieu.json --gioi-han 200

GIỚI HẠN, PHẢI NÓI RÕ. Bộ này CHỈ có metadata. Nó KHÔNG có:
  · điểm tác động 21 ngành  → mọi trang sẽ ghi "Chưa chấm điểm tác động"
  · quan hệ dẫn chiếu       → mục "Văn bản liên quan" trống
  · thân biểu mẫu           → trang biểu mẫu không có phần nội dung
Nên đây là bản để KIỂM GIAO DIỆN VÀ ĐƯỜNG DẪN, không phải bản để đăng.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Cờ phạm vi trong du-lieu.json được nén còn "tw"/"tinh"; DB dùng tên đầy đủ.
_PHAM_VI = {"tw": "trung_uong", "tinh": "tinh"}


def _ngay(s: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(s) if s else None
    except ValueError:
        return None


def nap(duong_json: Path, gioi_han: int | None = None) -> tuple[int, int]:
    """Đổ metadata vào kho. Trả về (số văn bản, số biểu mẫu)."""
    from src.storage.database import get_session, init_db, upsert_document
    from src.storage.models import LegalForm

    goi = json.loads(duong_json.read_text(encoding="utf-8"))
    # `eff_state` KHÔNG ghi thẳng được: apply_derived_facts() tự tính lại nó từ
    # `eff_status` ở mọi đường ghi. Truyền eff_state vào thì nó bị đè, cả kho
    # thành "khong_ro", và bộ lọc mặc định của trang trợ lý ("Còn hiệu lực")
    # giấu sạch — trang lên nhưng danh sách trống, trông y hệt kho rỗng.
    # du-lieu.json có sẵn bảng tra mã → nhãn, dùng đúng nó.
    nhan_hl = goi.get("hieu_luc_vb", {})
    van_ban = goi.get("van_ban", [])
    bieu_mau = goi.get("bieu_mau", [])
    if gioi_han:
        van_ban = van_ban[:gioi_han]
        bieu_mau = bieu_mau[:gioi_han]

    init_db()
    n_vb = n_bm = 0
    with get_session() as s:
        for i, v in enumerate(van_ban):
            so = (v.get("n") or "").strip()
            if not so:
                continue
            upsert_document(s, {
                "doc_num": so,
                "title": v.get("t") or so,
                "doc_type": v.get("l") or "",
                "moj_id": f"demo-{i}",
                "hierarchy_level": v.get("c"),
                "eff_status": nhan_hl.get(v.get("e"), ""),
                "issue_date": _ngay(v.get("d", "")),
                "territorial_scope": _PHAM_VI.get(v.get("p"), "trung_uong"),
                "tvpl_field_code": v.get("f"),
                "gdrive_fulltext_link": (
                    f"https://drive.google.com/file/d/{v['g']}/view"
                    if v.get("g") else None),
            })
            n_vb += 1
        s.commit()

        for b in bieu_mau:
            khoa = (b.get("k") or "").strip()
            if not khoa:
                continue
            if s.query(LegalForm).filter_by(form_key=khoa).first():
                continue
            s.add(LegalForm(
                form_key=khoa,
                source=khoa.split("-")[0] or "hopdong",
                external_id=khoa.split("-")[-1],
                title=b.get("t") or khoa,
                is_business=True,
                crawl_status="OK",
                nghiep_vu=json.dumps(b.get("v") or [], ensure_ascii=False),
                eff_state=b.get("e"),
                gdrive_docx_link=(
                    f"https://drive.google.com/file/d/{b['g']}/view"
                    if isinstance(b.get("g"), str) else None),
            ))
            n_bm += 1
        s.commit()
    return n_vb, n_bm


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tu", required=True, help="Đường dẫn tới du-lieu.json")
    ap.add_argument("--gioi-han", type=int, default=None,
                    help="Chỉ nạp N mục đầu, cho nhanh")
    a = ap.parse_args()

    p = Path(a.tu)
    if not p.is_file():
        raise SystemExit(f"Không thấy file: {p}")

    n_vb, n_bm = nap(p, a.gioi_han)
    print(f"\n=== Đã nạp kho DEMO ===")
    print(f"  văn bản  {n_vb}")
    print(f"  biểu mẫu {n_bm}")
    print("\nĐây là bản CHỈ CÓ METADATA — không có điểm tác động, không có quan")
    print("hệ dẫn chiếu, không có thân biểu mẫu. Dùng để xem giao diện và kiểm")
    print("đường dẫn, KHÔNG dùng để đăng.")
    print("\nDựng trang:")
    print("  python -m scripts.publish_site --html --out build/site")


if __name__ == "__main__":
    main()
