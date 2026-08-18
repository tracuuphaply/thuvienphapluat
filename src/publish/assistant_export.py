"""
Bộ dữ liệu gọn cho trang trợ lý pháp lý.

VÌ SAO KHÔNG DÙNG contentIndex.json CỦA QUARTZ. Đo ngày 19/08/2026: file đó 16,77 MB
thô (gzip 1,72 MB) cho 4.308 trang, trong đó 77% là trường `content` — toàn văn từng
trang, phục vụ tìm kiếm. Ba bên tiêu thụ cùng nạp và `JSON.parse` 16,77 MB đó trên
luồng chính. Trang trợ lý chỉ cần metadata để lọc và tra, nên nó dùng bộ riêng ~200×
nhỏ hơn.

TÊN TRƯỜNG VIẾT TẮT MỘT CHỮ CÁI là cố ý, không phải tiết kiệm vô nghĩa: với 4.200
văn bản thì mỗi ký tự tên trường nhân lên 4.200 lần. Đổi "so_hieu" thành "n" cắt
~50 KB. Bảng giải nghĩa nằm ngay dưới đây và trong chính file JSON (khoá `_truong`)
để bên đọc không phải đoán.

ĐỒ THỊ: ship DANH SÁCH KỀ, KHÔNG ship bố cục. Đây là điểm khác căn bản với Quartz —
nó dựng mô phỏng lực cho toàn bộ 4.308 nút, còn trang trợ lý chỉ vẽ LÁNG GIỀNG của
văn bản đang mở (bậc 1–2). Sơ đồ 4.308 nút không bao giờ đọc được, kể cả khi vẽ đủ
nhanh; thứ có ích là "văn bản này dẫn chiếu ai, ai dẫn chiếu nó".
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import text

from src.forms import effectivity as bm_eff
from src.legal.form_taxonomy import NGHIEP_VU
from src.legal.tvpl_fields import TEN_THEO_MA
from src.obsidian.config_obsidian import HIERARCHY_LABELS
from src.storage.models import LegalForm, LegalFormRef

logger = logging.getLogger(__name__)

TEN_FILE = "du-lieu.json"

#: Giải nghĩa tên trường viết tắt — cũng được nhúng vào JSON để bên đọc tự tra.
GIAI_NGHIA_TRUONG = {
    "van_ban": {
        "s": "slug trang công khai",
        "n": "số hiệu",
        "t": "tiêu đề",
        "l": "loại văn bản",
        "f": "mã lĩnh vực TVPL 1-27",
        "e": "cờ hiệu lực",
        "d": "ngày ban hành",
        "c": "cấp hiệu lực pháp lý 1-9",
        "p": "phạm vi: tw | tinh",
    },
    "bieu_mau": {
        "s": "slug trang công khai",
        "k": "form_key",
        "t": "tiêu đề",
        "v": "nhóm nghiệp vụ",
        "e": "cờ hiệu lực biểu mẫu",
        "g": "đã bị nguồn gỡ (1) hay không",
        "w": "tên file .docx",
        "p": "tên file .pdf",
        "c": "số hiệu căn cứ",
    },
    "do_thi": {
        "nut": "chỉ số trỏ vào mảng van_ban",
        "canh": "[nguồn, đích, loại quan hệ] — chỉ số, không phải slug",
        "quan_he": "bảng tra loại quan hệ",
    },
}


@dataclass
class ThongKeXuat:
    van_ban: int = 0
    bieu_mau: int = 0
    canh: int = 0
    kich_thuoc_kb: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _van_ban(session) -> tuple[list[dict], dict[str, int]]:
    """Metadata mọi văn bản đã đăng, kèm bảng tra slug → chỉ số."""
    rows = session.execute(text("""
        SELECT public_slug, doc_num, title, doc_type, tvpl_field_code,
               eff_state, issue_date, hierarchy_level, territorial_scope
        FROM documents
        WHERE public_slug IS NOT NULL AND is_vbqppl = 1
        ORDER BY public_slug
    """)).fetchall()

    ds, chi_so = [], {}
    for i, r in enumerate(rows):
        chi_so[r[0]] = i
        ds.append({
            "s": r[0],
            "n": r[1],
            "t": (r[2] or "")[:190],
            "l": r[3] or "",
            "f": r[4] or 27,
            "e": r[5] or "khong_ro",
            "d": str(r[6]) if r[6] else "",
            "c": r[7] or 99,
            "p": "tw" if r[8] == "trung_uong" else "tinh",
        })
    return ds, chi_so


def _bieu_mau(session) -> list[dict]:
    """Biểu mẫu doanh nghiệp đã đăng, kèm tên file tải về và số hiệu căn cứ."""
    forms = (
        session.query(LegalForm)
        .filter(LegalForm.is_business.is_(True))
        .filter(LegalForm.public_slug.isnot(None))
        .order_by(LegalForm.form_key)
        .all()
    )
    can_cu: dict[str, list[str]] = {}
    for r in session.query(LegalFormRef).all():
        can_cu.setdefault(r.form_key, []).append(r.doc_num)

    ds = []
    for f in forms:
        muc = {
            "s": f.public_slug,
            "k": f.form_key,
            "t": (f.title or "")[:190],
            "v": json.loads(f.nghiep_vu or "[]"),
            "e": f.eff_state or bm_eff.KHONG_RO,
            "c": can_cu.get(f.form_key, [])[:4],
        }
        if f.delisted_at:
            muc["g"] = 1
        if f.docx_path:
            muc["w"] = Path(f.docx_path).name
        if f.pdf_path:
            muc["p"] = Path(f.pdf_path).name
        ds.append(muc)
    return ds


def _do_thi(session, chi_so: dict[str, int]) -> dict:
    """Danh sách kề giữa các văn bản ĐÃ ĐĂNG, dạng chỉ số.

    Dùng chỉ số thay cho slug: 45.000 cạnh × 2 slug × ~22 ký tự = 2 MB, còn chỉ số
    thì ~0,4 MB. Cạnh trỏ tới văn bản chưa có trang bị BỎ, không giữ nửa cạnh —
    cạnh treo lơ lửng không vẽ được và cũng không nói lên điều gì.

    KHÔNG có nút TAG ở đây, cố ý. Trong sơ đồ Quartz, 17 nút tag sinh ra 12.600
    cạnh (22% toàn bộ) và riêng "van-ban-ngu-canh" có 3.255 cạnh — một nút như vậy
    hút cả phần ba sơ đồ vào một cục. Tag là bộ lọc, không phải quan hệ pháp lý.
    """
    rows = session.execute(text("""
        SELECT s.public_slug, t.public_slug, r.relation_type
        FROM document_references r
        JOIN documents s ON s.id = r.source_doc_id
        JOIN documents t ON t.doc_num = r.target_doc_num
        WHERE s.public_slug IS NOT NULL AND t.public_slug IS NOT NULL
    """)).fetchall()

    loai: list[str] = []
    ma_loai: dict[str, int] = {}
    canh: set[tuple[int, int, int]] = set()

    for nguon, dich, quan_he in rows:
        i, j = chi_so.get(nguon), chi_so.get(dich)
        if i is None or j is None or i == j:
            continue
        qh = quan_he or "Chưa xác định"
        if qh not in ma_loai:
            ma_loai[qh] = len(loai)
            loai.append(qh)
        canh.add((i, j, ma_loai[qh]))

    return {"quan_he": loai, "canh": sorted(canh)}


def xuat_du_lieu(session, out_dir: Path) -> ThongKeXuat:
    """Ghi bộ dữ liệu cho trang trợ lý. Trả về thống kê.

    Ghi MỘT file: trang trợ lý là trang tĩnh trên GitHub Pages, mỗi file thêm là
    một lượt tải thêm và một chỗ để hai bên lệch phiên bản.
    """
    van_ban, chi_so = _van_ban(session)
    bieu_mau = _bieu_mau(session)
    do_thi = _do_thi(session, chi_so)

    goi = {
        "tao_luc": date.today().isoformat(),
        "_truong": GIAI_NGHIA_TRUONG,
        "linh_vuc": [{"ma": ma, "ten": ten} for ma, ten in sorted(TEN_THEO_MA.items())],
        "nghiep_vu": [{"ma": ma, "ten": ten} for ma, ten in NGHIEP_VU.items()],
        "hieu_luc_vb": {
            "con_hieu_luc": "Còn hiệu lực",
            "het_toan_bo": "Hết hiệu lực toàn bộ",
            "het_mot_phan": "Hết hiệu lực một phần",
            "chua_hieu_luc": "Chưa có hiệu lực",
            "khong_ro": "Chưa xác minh",
        },
        "hieu_luc_bm": dict(bm_eff.NHAN),
        "cap": {str(k): v for k, v in HIERARCHY_LABELS.items()},
        "van_ban": van_ban,
        "bieu_mau": bieu_mau,
        "do_thi": do_thi,
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    duong_dan = out_dir / TEN_FILE
    # separators không khoảng trắng: với 45.000 cạnh thì mỗi khoảng trắng sau dấu
    # phẩy là thêm ~90 KB.
    noi_dung = json.dumps(goi, ensure_ascii=False, separators=(",", ":"))
    duong_dan.write_text(noi_dung, encoding="utf-8")

    tk = ThongKeXuat(
        van_ban=len(van_ban), bieu_mau=len(bieu_mau),
        canh=len(do_thi["canh"]), kich_thuoc_kb=len(noi_dung.encode()) // 1024,
    )
    logger.info("Xuất dữ liệu trợ lý: %d văn bản, %d biểu mẫu, %d cạnh, %d KB",
                tk.van_ban, tk.bieu_mau, tk.canh, tk.kich_thuoc_kb)
    return tk


def chep_ung_dung(out_dir: Path) -> Path:
    """Chép index.html của trang trợ lý sang thư mục xuất.

    Ứng dụng là MỘT file tĩnh tự chứa, không có bước build, không phụ thuộc thư
    viện ngoài. Chép chứ không sinh ra: nó là mã nguồn được người viết và soát,
    không phải sản phẩm của một khuôn mẫu.
    """
    import shutil

    nguon = Path(__file__).parent / "tro_ly" / "index.html"
    dich = Path(out_dir) / "index.html"
    dich.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(nguon, dich)
    return dich


__all__ = ["TEN_FILE", "GIAI_NGHIA_TRUONG", "ThongKeXuat", "xuat_du_lieu",
           "chep_ung_dung"]
