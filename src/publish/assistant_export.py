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
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import text

from src.forms import effectivity as bm_eff
from src.legal.form_taxonomy import NGHIEP_VU, NGHIEP_VU_CA_NHAN
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
        "r": "có mảnh ruột ở noi-dung/van-ban/{s}.html (vắng nghĩa là không có)",
        "a": "cơ quan ban hành (vắng nếu kho chưa xác định)",
        "h": "ngày có hiệu lực (vắng nếu nguồn không công bố)",
        "g": "ID file toàn văn trên Google Drive — ghép "
             "https://drive.google.com/file/d/{g}/view (vắng nếu chưa có)",
    },
    # `x` tách RIÊNG khỏi `g`, và đây là lỗi đã xảy ra thật chứ không phải dọn dẹp
    # cho gọn: cả cờ đã-gỡ lẫn ID Drive từng cùng viết vào `g`, dòng ghi ID chạy
    # sau nên đè mất cờ. Hệ quả đo trên bản đang chạy: 653/653 biểu mẫu có ID Drive
    # → `g` truthy → trang trợ lý hiện cảnh báo đỏ "Nguồn đã gỡ biểu mẫu này,
    # không nên dùng để nộp" cho TOÀN BỘ kho, còn mẫu bị gỡ thật thì không phân
    # biệt được nữa. Bảng giải nghĩa ngay dưới đây cũng đã khai `g` hai lần —
    # Python lặng lẽ lấy khai báo sau, nên chính bảng tự mô tả cũng nói sai.
    "bieu_mau": {
        "s": "slug trang công khai",
        "k": "form_key",
        "t": "tiêu đề",
        "v": "nhóm nghiệp vụ",
        "e": "cờ hiệu lực biểu mẫu",
        "x": "đã bị nguồn gỡ (1) hay không",
        "b": "phục vụ doanh nghiệp (1)",
        "i": "phục vụ cá nhân (1)",
        "vc": "nhóm nghiệp vụ cá nhân — tra trong nghiep_vu_ca_nhan",
        "x": "đã bị nguồn gỡ khỏi trang liệt kê (1) — vắng nghĩa là chưa gỡ",
        "w": "tên file .docx",
        "p": "tên file .pdf",
        "c": "số hiệu căn cứ",
        "r": "có mảnh ruột ở noi-dung/bieu-mau/{s}.html (vắng nghĩa là không có)",
        "g": "ID file .docx trên Google Drive — ghép "
             "https://drive.google.com/file/d/{g}/view (vắng nếu chưa tải lên)",
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


_RE_ID_DRIVE = re.compile(r"/d/([A-Za-z0-9_-]{10,})")


def _id_drive(link: str) -> str:
    """Rút ID file từ URL Drive; trả về chuỗi rỗng nếu không nhận ra dạng.

    Ship ID chứ không ship URL: tiền tố "https://drive.google.com/file/d/" dài 32
    ký tự và lặp lại y hệt ở 3.883 văn bản — ~124 KB không mang thông tin nào.
    """
    m = _RE_ID_DRIVE.search(link or "")
    return m.group(1) if m else ""


def _van_ban(session, co_ruot: set[str] | None = None) -> tuple[list[dict], dict[str, int]]:
    """Metadata mọi văn bản đã đăng, kèm bảng tra slug → chỉ số."""
    rows = session.execute(text("""
        SELECT public_slug, doc_num, title, doc_type, tvpl_field_code,
               eff_state, issue_date, hierarchy_level, territorial_scope,
               gdrive_fulltext_link, agency_name, eff_from
        FROM documents
        WHERE public_slug IS NOT NULL AND is_vbqppl = 1
        ORDER BY public_slug
    """)).fetchall()

    ds, chi_so = [], {}
    for i, r in enumerate(rows):
        chi_so[r[0]] = i
        muc = {
            "s": r[0],
            "n": r[1],
            "t": (r[2] or "")[:190],
            "l": r[3] or "",
            "f": r[4] or 27,
            "e": r[5] or "khong_ro",
            "d": str(r[6]) if r[6] else "",
            "c": r[7] or 99,
            "p": "tw" if r[8] == "trung_uong" else "tinh",
        }
        # Cờ CÓ RUỘT. Trang trợ lý phải biết TRƯỚC khi bấm là tài liệu này có
        # nội dung để tải hay không: đoán rồi tải thử thì mỗi tài liệu không có
        # ruột là một lượt 404 và một dòng đỏ trong bảng điều khiển, mà người
        # dùng vẫn phải chờ hết lượt tải mới biết là không có gì.
        if co_ruot is not None and r[0] in co_ruot:
            muc["r"] = 1
        # Cơ quan ban hành và ngày có hiệu lực: trang Quartz vẫn hiện hai dữ kiện
        # này, trang trợ lý thì không — vì bộ xuất không lấy chúng. Với người tra
        # cứu pháp luật, "ai ban hành" là dữ kiện đọc đầu tiên. Chỉ ghi khi có
        # giá trị, để không phình bộ dữ liệu bằng chuỗi rỗng.
        if r[10]:
            muc["a"] = r[10]
        if r[11]:
            muc["h"] = str(r[11])
        # Chỉ ship ID, không ship cả URL: 3.883 link × 39 ký tự tiền tố giống hệt
        # nhau là ~150 KB lặp lại. Bên đọc tự ghép — quy tắc ghép nằm ngay trong
        # bảng giải nghĩa trường.
        if r[9]:
            muc["g"] = _id_drive(r[9])
        ds.append(muc)
    return ds, chi_so


def _bieu_mau(session) -> list[dict]:
    """Biểu mẫu đã đăng (doanh nghiệp hoặc cá nhân), kèm tên file và căn cứ."""
    from src.forms.store import loc_dang_cong_khai

def _bieu_mau(session, co_ruot: set[str] | None = None) -> list[dict]:
    """Biểu mẫu doanh nghiệp đã đăng, kèm tên file tải về và số hiệu căn cứ."""
    forms = (
        loc_dang_cong_khai(session.query(LegalForm))
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
        # Khoá "x", KHÔNG dùng lại "g". Bản trước đặt cả cờ bị-gỡ lẫn ID Drive
        # vào cùng khoá "g", nên mẫu vừa bị gỡ vừa có bản Drive thì cờ bị ghi đè
        # và biến mất. Chưa hỏng dữ liệu lúc phát hiện — 0 mẫu bị gỡ — nhưng là
        # bẫy nằm chờ: cả 2.467 mẫu nay đều có link Drive, nên mẫu đầu tiên bị
        # nguồn gỡ sẽ mất cờ mà không ai thấy. Bảng mô tả trường cũng khai "g"
        # hai lần, và Python chỉ giữ cái sau.
        if f.delisted_at:
            muc["x"] = 1
        if f.is_business:
            muc["b"] = 1
        if f.is_individual:
            muc["i"] = 1
        # Chỉ xuất nhóm cá nhân cho mẫu THẬT SỰ phục vụ cá nhân. Phễu đặt nhóm
        # mặc định cho mọi mẫu mà không kiểm cờ, nên 3 mẫu chỉ phục vụ doanh
        # nghiệp vẫn mang nhóm "khac_ca_nhan" — bên đọc lọc theo "vc" sẽ thấy
        # chúng lọt vào danh mục cá nhân. Ràng ở đây để bản bàn giao tự nhất
        # quán, thay vì bắt mỗi nơi tiêu thụ tự kiểm chéo với cờ "i".
        if f.is_individual and f.nghiep_vu_ca_nhan:
            muc["vc"] = json.loads(f.nghiep_vu_ca_nhan or "[]")
        if co_ruot is not None and f.public_slug in co_ruot:
            muc["r"] = 1
        if f.delisted_at:
            muc["x"] = 1
        if f.docx_path:
            muc["w"] = Path(f.docx_path).name
        if f.pdf_path:
            muc["p"] = Path(f.pdf_path).name
        if f.gdrive_docx_link:
            muc["g"] = _id_drive(f.gdrive_docx_link)
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


def xuat_du_lieu(session, out_dir: Path,
                 ruot_vb: set[str] | None = None,
                 ruot_bm: set[str] | None = None) -> ThongKeXuat:
    """Ghi bộ dữ liệu cho trang trợ lý. Trả về thống kê.

    Ghi MỘT file: trang trợ lý là trang tĩnh trên GitHub Pages, mỗi file thêm là
    một lượt tải thêm và một chỗ để hai bên lệch phiên bản.
    """
    van_ban, chi_so = _van_ban(session, ruot_vb)
    bieu_mau = _bieu_mau(session, ruot_bm)
    do_thi = _do_thi(session, chi_so)

    goi = {
        "tao_luc": date.today().isoformat(),
        "_truong": GIAI_NGHIA_TRUONG,
        "linh_vuc": [{"ma": ma, "ten": ten} for ma, ten in sorted(TEN_THEO_MA.items())],
        "nghiep_vu": [{"ma": ma, "ten": ten} for ma, ten in NGHIEP_VU.items()],
        # 15 nhóm theo SỰ KIỆN ĐỜI NGƯỜI, tập riêng với 12 nhóm nghiệp vụ doanh
        # nghiệp. Thiếu bảng này thì phía đọc không dịch được mã trong trường
        # "vc" thành tên hiển thị.
        "nghiep_vu_ca_nhan": [{"ma": ma, "ten": ten}
                              for ma, ten in NGHIEP_VU_CA_NHAN.items()],
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
