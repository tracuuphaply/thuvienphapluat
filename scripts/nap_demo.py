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

GIỚI HẠN, PHẢI NÓI RÕ. Bộ này CHỈ có những gì `du-lieu.json` mang theo. Nó có
metadata và có QUAN HỆ DẪN CHIẾU (dựng lại từ khối `do_thi`), nhưng KHÔNG có:
  · điểm tác động 21 ngành  → mọi trang sẽ ghi "Chưa chấm điểm tác động"
  · thân biểu mẫu           → trang biểu mẫu không có phần nội dung
Nên đây là bản để KIỂM GIAO DIỆN VÀ ĐƯỜNG DẪN, không phải bản để đăng.

VÌ SAO PHẢI NẠP CẢ QUAN HỆ. Bản đầu bỏ qua khối `do_thi`, và hệ quả không dừng ở
"mục Văn bản liên quan trống" như đã ghi ở đây. Sơ đồ quan hệ ở chế độ toàn kho
chỉ nhận nút CÓ ÍT NHẤT MỘT CẠNH (`S.ke.has(i)` trong tro_ly/index.html), nên kho
0 cạnh cho ra đúng MỘT nút — chính văn bản đang mở. Trên màn hình nó hiện ra là
"Toàn kho · 1 văn bản", trông y như bộ đồ thị hỏng chứ không như dữ liệu thiếu.
Mà 23.801 cạnh ấy nằm sẵn trong file nguồn, chỉ là chưa ai đọc.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Cờ phạm vi trong du-lieu.json được nén còn "tw"/"tinh"; DB dùng tên đầy đủ.
_PHAM_VI = {"tw": "trung_uong", "tinh": "tinh"}


def _ngay(s: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(s) if s else None
    except ValueError:
        return None


def nap(duong_json: Path, gioi_han: int | None = None) -> tuple[int, int, int]:
    """Đổ metadata và quan hệ vào kho. Trả về (số văn bản, số biểu mẫu, số cạnh)."""
    from src.storage.database import get_session, init_db, upsert_document
    from src.storage.models import DocumentReference, LegalForm

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
        # Cạnh trong `do_thi` là CHỈ SỐ vào mảng van_ban ĐẦY ĐỦ. Cắt mảng rồi mới
        # soi chỉ số thì cạnh trỏ lệch sang văn bản khác — sai âm thầm, đồ thị
        # vẫn vẽ ra được nên không ai biết. Cắt xong thì chỉ giữ cạnh có CẢ HAI
        # đầu còn nằm trong phần đã cắt.
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

        n_canh = _nap_quan_he(s, goi, van_ban, DocumentReference)
    return n_vb, n_bm, n_canh


def _nap_quan_he(s, goi: dict, van_ban: list, DocumentReference) -> int:
    """Dựng lại `document_references` từ khối `do_thi`. Trả về số cạnh đã ghi.

    Cạnh trong file là bộ ba chỉ số `[nguồn, đích, loại]`; kho thì nối bằng
    `source_doc_id` (khoá ngoại) và `target_doc_num` (SỐ HIỆU, không phải id) —
    đúng cặp mà `assistant_export._do_thi()` join lại khi xuất. Ghi sai một
    trong hai đầu là cạnh biến mất lúc xuất chứ không báo lỗi lúc nạp.
    """
    do_thi = goi.get("do_thi") or {}
    canh = do_thi.get("canh") or []
    ten_quan_he = do_thi.get("quan_he") or []
    if not canh:
        return 0

    n = len(van_ban)
    # Tra id theo số hiệu, MỘT LẦN. Hỏi kho từng cạnh là 23.801 lượt truy vấn.
    id_theo_so = dict(
        s.execute(text("SELECT doc_num, id FROM documents")).fetchall())

    hang, da_co = [], set()
    for c in canh:
        if len(c) < 2:
            continue
        i, j = c[0], c[1]
        # Cả hai đầu phải nằm trong phần đã nạp. Nửa cạnh không vẽ được, và
        # `_do_thi()` cũng bỏ nó lúc xuất — giữ lại chỉ tổ phình kho.
        if not (0 <= i < n and 0 <= j < n) or i == j:
            continue
        so_nguon = (van_ban[i].get("n") or "").strip()
        so_dich = (van_ban[j].get("n") or "").strip()
        id_nguon = id_theo_so.get(so_nguon)
        if not id_nguon or not so_dich or so_dich not in id_theo_so:
            continue
        loai = c[2] if len(c) > 2 else None
        ten = ten_quan_he[loai] if isinstance(loai, int) and loai < len(ten_quan_he) \
            else "Chưa xác định"
        # Số hiệu KHÔNG duy nhất trong kho: 300 mục đầu của file gộp lại còn 297
        # văn bản. Hai mục trùng số hiệu cho ra cùng một cặp cạnh, nên phải khử
        # trùng ở đây — không thì kho có cạnh lặp còn đồ thị thì không đổi.
        khoa = (id_nguon, so_dich, ten)
        if khoa in da_co:
            continue
        da_co.add(khoa)
        hang.append({
            "source_doc_id": id_nguon,
            "target_doc_num": so_dich,
            "relation_type": ten,
            "target_doc_id": id_theo_so.get(so_dich),
        })

    if hang:
        s.bulk_insert_mappings(DocumentReference, hang)
        s.commit()
    return len(hang)


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

    n_vb, n_bm, n_canh = nap(p, a.gioi_han)
    print(f"\n=== Đã nạp kho DEMO ===")
    print(f"  văn bản  {n_vb}")
    print(f"  biểu mẫu {n_bm}")
    print(f"  quan hệ  {n_canh}")
    if not n_canh:
        # Nói thẳng ra, vì triệu chứng của nó trên giao diện là "Toàn kho · 1
        # văn bản" — trông như đồ thị hỏng chứ không như kho thiếu quan hệ.
        print("  ⚠ Không có quan hệ nào — sơ đồ liên kết sẽ chỉ hiện MỘT nút.")
        print("    Kiểm lại: du-lieu.json nguồn có khối \"do_thi\" với cạnh không?")
    print("\nĐây là bản KHÔNG có điểm tác động và KHÔNG có thân biểu mẫu.")
    print("Dùng để xem giao diện và kiểm đường dẫn, KHÔNG dùng để đăng.")
    print("\nDựng trang:")
    print("  python -m scripts.publish_site --html --out build/site")


if __name__ == "__main__":
    main()
