"""
Đọc kho biểu mẫu từ một checkout `legal-vault-public`.

ĐỌC TỪ VAULT, KHÔNG ĐỌC TỪ DB. Bên xuất bản nạp chính checkout này, nên hai bên
phải nhìn cùng một bản dữ liệu. Đọc thẳng SQLite của repo làm việc thì sinh bài
cho những biểu mẫu chưa đăng — bên kia không có `form_key` tương ứng và bài bị
bỏ trong im lặng.

HAI NGUỒN TRONG MỘT CHECKOUT:
    <vault>/tro-ly/du-lieu.json      chỉ mục gọn (biểu mẫu + văn bản + đồ thị)
    <vault>/content/bieu-mau/<s>.md  trang biểu mẫu, chứa ruột tờ mẫu

Ruột tờ mẫu KHÔNG nằm trong `du-lieu.json` (cố ý — chỉ mục là metadata để lọc,
mỗi ruột mẫu vài KB × 653 mẫu là một file 2 MB không ai cần tải hết). Nó nằm
trong trang `.md`, ở mục `## Nội dung biểu mẫu`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

TEN_FILE_CHI_MUC = "du-lieu.json"
THU_MUC_TRO_LY = "tro-ly"
THU_MUC_BIEU_MAU = "content/bieu-mau"

#: Mục chứa ruột tờ mẫu trong trang `.md`, và mục chặn cuối.
#: Khớp đúng PAGE_TEMPLATE của src/publish/form_exporter.py.
_MO_RUOT = "## Nội dung biểu mẫu"
_HET_RUOT = "## Nguồn"

#: Số ký tự tối thiểu để coi là có ruột mẫu thật. Vài trang chỉ có một dòng
#: "Đang cập nhật" — sinh bài từ đó là sinh bài từ hư không.
NGUONG_RUOT_MAU = 400


class KhoKhongDoc(RuntimeError):
    """Không đọc được checkout vault. Dừng hẳn thay vì sinh bài từ kho rỗng."""


@dataclass(frozen=True)
class VanBan:
    """Một văn bản trong chỉ mục — dùng làm căn cứ cho biểu mẫu."""

    so_hieu: str
    tieu_de: str
    slug: str
    hieu_luc: str
    drive_toan_van: str = ""

    @property
    def co_toan_van(self) -> bool:
        return bool(self.drive_toan_van)


@dataclass
class BieuMau:
    """Một biểu mẫu đã đăng, đủ dữ kiện để viết bài hướng dẫn về nó."""

    form_key: str
    slug: str
    tieu_de: str
    nghiep_vu: list[str] = field(default_factory=list)
    hieu_luc: str = "khong_ro"
    can_cu: list[str] = field(default_factory=list)
    da_go: bool = False
    ruot_mau: str = ""
    duong_dan_md: Path | None = None

    @property
    def co_ruot_mau(self) -> bool:
        return len(self.ruot_mau) >= NGUONG_RUOT_MAU

    def nguon_hash(self) -> str:
        """Vân tay của NGUỒN sinh ra bài này.

        Gồm cả `hieu_luc` và `can_cu`, không chỉ ruột mẫu — văn bản căn cứ hết
        hiệu lực là lý do chính đáng nhất để viết lại bài, mà ruột tờ mẫu thì
        không đổi một ký tự nào khi điều đó xảy ra. Băm mỗi ruột mẫu thì bài cũ
        nằm im trong khi căn cứ của nó đã chết.

        Tiêu đề cũng vào băm: Thư viện Pháp luật sửa chữ tiêu đề khá thường, và
        tiêu đề đổi thì tiêu đề bài nên được viết lại.
        """
        nguyen_lieu = "␟".join([
            self.tieu_de,
            self.hieu_luc,
            "␞".join(sorted(self.can_cu)),
            self.ruot_mau,
        ])
        return hashlib.sha256(nguyen_lieu.encode("utf-8")).hexdigest()


@dataclass
class Kho:
    """Toàn bộ dữ kiện đọc được từ một checkout vault."""

    bieu_mau: list[BieuMau]
    van_ban: dict[str, VanBan]          # số hiệu (đã chuẩn hoá) → văn bản
    nghiep_vu: dict[str, str]           # mã → nhãn
    hieu_luc_bm: dict[str, str]         # mã → nhãn
    tao_luc: str = ""

    def tra_van_ban(self, so_hieu: str) -> VanBan | None:
        return self.van_ban.get(chuan_hoa_so_hieu(so_hieu))

    def theo_khoa(self) -> dict[str, BieuMau]:
        return {bm.form_key: bm for bm in self.bieu_mau}


def chuan_hoa_so_hieu(num: str) -> str:
    """Khoá tra cứu số hiệu — dùng chung quy tắc với cổng đối chiếu trích dẫn.

    Nhập lại `_norm_key` của src/rag/citation_check.py để "168/2025/ND-CP" và
    "168/2025/NĐ-CP" tra ra cùng một văn bản. Hai bảng khoá lệch nhau thì cổng
    trích dẫn cho qua đúng thứ mà bảng tra căn cứ ở đây lại không tìm thấy.
    """
    from src.rag.citation_check import _norm_key

    return _norm_key(num or "")


def ruot_mau_tu_trang(noi_dung: str) -> str:
    """Cắt mục `## Nội dung biểu mẫu` khỏi trang `.md`, giữ nguyên xuống dòng.

    Cắt đúng cách bên xuất bản cắt. Nếu hai bên cắt lệch nhau thì mô hình đọc
    một tờ mẫu còn người đọc thấy một tờ khác.
    """
    i = noi_dung.find(_MO_RUOT)
    if i < 0:
        return ""
    than = noi_dung[i + len(_MO_RUOT):]
    j = than.find(_HET_RUOT)
    if j >= 0:
        than = than[:j]
    return than.strip()


def _doc_chi_muc(vault: Path) -> dict:
    duong_dan = vault / THU_MUC_TRO_LY / TEN_FILE_CHI_MUC
    try:
        return json.loads(duong_dan.read_text(encoding="utf-8"))
    except OSError as e:
        raise KhoKhongDoc(
            f"Không đọc được chỉ mục {duong_dan}. Đây có phải checkout "
            f"legal-vault-public không? ({e})"
        ) from e
    except json.JSONDecodeError as e:
        raise KhoKhongDoc(f"Chỉ mục {duong_dan} hỏng: {e}") from e


_RE_DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def _drive_id_bieu_mau(gia_tri) -> tuple[str, bool]:
    """Tách trường `g` của biểu mẫu thành (id Drive, đã bị gỡ).

    TRƯỜNG `g` BỊ DÙNG CHO HAI VIỆC trong bộ xuất chỉ mục
    (src/publish/assistant_export.py): `1` nghĩa là "nguồn đã gỡ biểu mẫu này",
    còn một chuỗi nghĩa là "ID file .docx trên Drive". Bản ghi nào có cả hai thì
    ID ghi đè cờ gỡ, nên cờ gỡ mất im lặng.

    Không sửa bộ xuất ở đây: định dạng đó đang được trang trợ lý tĩnh đọc, đổi
    là đổi hợp đồng với một bên khác. Đọc phòng thủ theo KIỂU giá trị, và ghi
    lại sự thật này ngay chỗ nó gây hại.
    """
    if gia_tri in (1, "1", True):
        return "", True
    if isinstance(gia_tri, str) and _RE_DRIVE_ID.match(gia_tri):
        return gia_tri, False
    return "", False


def doc_kho(vault: str | Path) -> Kho:
    """Nạp chỉ mục + ruột tờ mẫu từ một checkout `legal-vault-public`."""
    vault = Path(vault)
    goi = _doc_chi_muc(vault)

    if not isinstance(goi, dict):
        raise KhoKhongDoc(
            f"chỉ mục phải là đối tượng JSON, nhận {type(goi).__name__}")
    for ten in ("van_ban", "bieu_mau"):
        if goi.get(ten) is not None and not isinstance(goi[ten], list):
            raise KhoKhongDoc(
                f"trường {ten!r} của chỉ mục phải là mảng, nhận "
                f"{type(goi[ten]).__name__}")

    van_ban: dict[str, VanBan] = {}
    for muc in goi.get("van_ban") or []:
        if not isinstance(muc, dict):
            continue
        so_hieu = muc.get("n") or ""
        if not so_hieu:
            continue
        van_ban[chuan_hoa_so_hieu(so_hieu)] = VanBan(
            so_hieu=so_hieu,
            tieu_de=muc.get("t") or "",
            slug=muc.get("s") or "",
            hieu_luc=muc.get("e") or "khong_ro",
            drive_toan_van=muc.get("g") or "",
        )

    thu_muc_bm = vault / THU_MUC_BIEU_MAU
    thieu_trang = 0
    bieu_mau: list[BieuMau] = []
    for muc in goi.get("bieu_mau") or []:
        if not isinstance(muc, dict):
            continue
        khoa = muc.get("k") or ""
        if not khoa:
            continue
        slug = muc.get("s") or ""
        _, da_go = _drive_id_bieu_mau(muc.get("g"))

        # Ghép slug vào đường dẫn sau khi đã chốt nó không thoát khỏi thư mục
        # kho. Slug hiện do chính bộ xuất của repo này sinh ra nên lành, nhưng
        # `du-lieu.json` là file đọc từ MỘT REPO KHÁC — ràng buộc đó nằm ngoài
        # tầm với của module này, nên phải kiểm chứ không giả định.
        duong_dan = None
        if slug and "/" not in slug and "\\" not in slug and not slug.startswith("."):
            ung = thu_muc_bm / f"{slug}.md"
            if ung.resolve().parent == thu_muc_bm.resolve():
                duong_dan = ung

        ruot = ""
        if duong_dan and duong_dan.exists():
            ruot = ruot_mau_tu_trang(duong_dan.read_text(encoding="utf-8"))
        else:
            thieu_trang += 1
            duong_dan = None

        bieu_mau.append(BieuMau(
            form_key=khoa,
            slug=slug,
            tieu_de=muc.get("t") or "",
            nghiep_vu=list(muc.get("v") or []),
            hieu_luc=muc.get("e") or "khong_ro",
            can_cu=[c for c in (muc.get("c") or []) if c],
            da_go=da_go,
            ruot_mau=ruot,
            duong_dan_md=duong_dan,
        ))

    if thieu_trang:
        logger.warning(
            "%d/%d biểu mẫu không tìm thấy trang .md trong %s — chúng sẽ bị bỏ "
            "khi chọn ứng viên", thieu_trang, len(bieu_mau), thu_muc_bm,
        )

    return Kho(
        bieu_mau=bieu_mau,
        van_ban=van_ban,
        nghiep_vu={m["ma"]: m["ten"] for m in (goi.get("nghiep_vu") or [])},
        hieu_luc_bm=dict(goi.get("hieu_luc_bm") or {}),
        tao_luc=goi.get("tao_luc") or "",
    )


def db_so_hieu_tu_kho(kho: Kho, duong_dan: Path) -> Path:
    """Dựng một SQLite tối giản `documents(doc_num)` từ chỉ mục vault.

    VÌ SAO CẦN: `check_citations()` đối chiếu với `data/legal_docs.db` — file đó
    cố ý không nằm trong git (`.gitignore`: `*.db`) nên trên máy chạy CI nó
    không tồn tại, và cổng bắt buộc sẽ hoặc vỡ hoặc chặn sạch mọi bài.

    Và đây là kho ĐÚNG để đối chiếu, không phải một bản thay thế tạm bợ: chỉ mục
    vault chính là tập văn bản mà bên xuất bản có trang để dẫn tới. Một số hiệu
    không có trong đó thì người đọc bấm vào cũng không tra được gì — đúng thứ mà
    cổng trích dẫn tồn tại để chặn. DB thật của repo làm việc là tập cha của nó;
    dùng bản ấy khi có (`--db`) thì cổng nới rộng ra, không xiết vào.
    """
    duong_dan = Path(duong_dan)
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    if duong_dan.exists():
        duong_dan.unlink()

    conn = sqlite3.connect(str(duong_dan))
    try:
        conn.execute("CREATE TABLE documents (doc_num TEXT)")
        conn.executemany(
            "INSERT INTO documents (doc_num) VALUES (?)",
            [(vb.so_hieu,) for vb in kho.van_ban.values()],
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Dựng DB đối chiếu trích dẫn từ vault: %d số hiệu → %s",
                len(kho.van_ban), duong_dan)
    return duong_dan


@dataclass(frozen=True)
class UngVien:
    """Một biểu mẫu đã được chấm điểm để xếp thứ tự sinh bài."""

    bieu_mau: BieuMau
    can_cu_khop: list[VanBan]
    diem: int

    @property
    def co_toan_van(self) -> bool:
        return any(vb.co_toan_van for vb in self.can_cu_khop)


def chon_ung_vien(
    kho: Kho,
    nghiep_vu: str = "",
    hieu_luc: str = "",
    chi_co_toan_van: bool = False,
) -> list[UngVien]:
    """Xếp biểu mẫu theo mức viết được bài sâu tới đâu, tốt nhất lên đầu.

    THỨ TỰ NÀY KHÔNG TUỲ Ý. 653 biểu mẫu, 74% mang cờ `khong_ro` — không căn cứ,
    không toàn văn, bài viết ra chỉ soi được chính tờ giấy. Nhóm viết được bài
    hướng dẫn thao tác sâu nhất là nhóm CÓ CĂN CỨ KHỚP KHO VÀ CÓ TOÀN VĂN trên
    Drive (~172 mẫu). Chạy cả 653 ngay là in ra hàng trăm bài mỏng — đúng định
    nghĩa scaled content mà cả hệ thống này đang tránh.

    Điểm: mỗi căn cứ có toàn văn 4 điểm, mỗi căn cứ khớp kho 2 điểm, còn hiệu
    lực rõ ràng 1 điểm. Biểu mẫu đã bị nguồn gỡ và biểu mẫu không có ruột mẫu bị
    LOẠI HẲN, không phải xếp cuối: viết hướng dẫn cho một tờ giấy không còn tồn
    tại ở đâu là tệ hơn không viết gì.
    """
    ds: list[UngVien] = []
    for bm in kho.bieu_mau:
        if bm.da_go or not bm.co_ruot_mau:
            continue
        if nghiep_vu and nghiep_vu not in bm.nghiep_vu:
            continue
        if hieu_luc and bm.hieu_luc != hieu_luc:
            continue

        khop = [vb for vb in (kho.tra_van_ban(c) for c in bm.can_cu) if vb]
        if chi_co_toan_van and not any(vb.co_toan_van for vb in khop):
            continue

        diem = 2 * len(khop) + 4 * sum(1 for vb in khop if vb.co_toan_van)
        if bm.hieu_luc not in ("khong_ro", ""):
            diem += 1
        ds.append(UngVien(bieu_mau=bm, can_cu_khop=khop, diem=diem))

    # form_key làm khoá phụ: cùng điểm thì thứ tự phải TẤT ĐỊNH, nếu không mỗi
    # lần chạy `--limit 20` lại ra một nhóm khác và trạng thái đã-sinh vô nghĩa.
    ds.sort(key=lambda u: (-u.diem, u.bieu_mau.form_key))
    return ds


__all__ = [
    "TEN_FILE_CHI_MUC", "NGUONG_RUOT_MAU", "KhoKhongDoc",
    "VanBan", "BieuMau", "Kho", "UngVien",
    "chuan_hoa_so_hieu", "ruot_mau_tu_trang", "doc_kho", "chon_ung_vien",
    "db_so_hieu_tu_kho",
]
