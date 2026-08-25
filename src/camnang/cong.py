"""
Ba cổng chặn chạy TRƯỚC khi ghi `bai.json`.

VÌ SAO CHẶN Ở ĐÂY chứ để bên xuất bản chặn: bên kia cũng chặn, nhưng ở đó bài
đã tốn một lượt gọi mô hình rồi mới bị loại, và người vận hành chỉ thấy một dòng
"bỏ 37 bài" sau khi chạy xong. Chặn tại chỗ sinh thì sửa được ngay — cổng tiêu
đề thậm chí sinh lại được với chỉ dẫn sửa lỗi.

Ba cổng:
    cong_tieu_de     tiêu đề mang dấu hiệu lấy từ ruột tờ mẫu  → sinh lại
    cong_hop_dong    trường thiếu/quá dài so với §1 hợp đồng   → loại
    cong_trich_dan   số hiệu không có trong kho lẫn trong nguồn → citation_ok=false
"""
from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from src.rag.citation_check import CitationReport, check_citations, extract_doc_nums, fold_dau

logger = logging.getLogger(__name__)


class KhoDoiChieuHong(RuntimeError):
    """Không mở được kho để đối chiếu trích dẫn — cổng bắt buộc không chạy được."""

# Ràng buộc trường, chép từ §1 hợp đồng bàn giao. Đổi ở đây là đổi hợp đồng —
# phải báo bên xuất bản trước.
TIEU_DE_MIN = 3
TIEU_DE_MAX = 200
MO_TA_MAX = 500

#: Trần cho riêng `than_bai`. Hợp đồng đặt trần 200.000 ký tự cho TOÀN BỘ HTML
#: một bài (hộp hiệu lực + thân bài + ruột mẫu + footer). Ruột mẫu thường vài KB
#: nhưng có mẫu lên tới vài chục KB, và HTML nở ra so với markdown — nên chặn
#: thân bài ở mức thấp hơn hẳn để phần còn lại luôn có chỗ. Bài đúng chuẩn
#: 900–1.600 chữ chỉ khoảng 6–12 KB, chạm trần này nghĩa là mô hình đang chép tờ
#: mẫu hoặc lặp vô hạn — cả hai đều phải loại, không phải cắt bớt.
THAN_BAI_MAX = 60_000


def _gap(s: str) -> str:
    """Chuẩn hoá để so khớp CỤM TỪ: bỏ dấu, hạ chữ thường, gộp mọi ký tự không

    phải chữ-số thành một khoảng trắng.

    Gộp ký tự phân cách là chỗ quan trọng: nó nuốt dấu chấm thừa cuối dòng, gạch
    ngang dài/ngắn, và mọi khoảng trắng lặp — nên "CỘNG HOÀ", "CỘNG HÒA", "CỘNG
    HÒA … VIỆT NAM." và dạng NFD của chúng đều rút về đúng một chuỗi.
    """
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"[^a-z0-9]+", " ", fold_dau(s).lower()).strip()


def _giu_dau_cau(s: str) -> str:
    """Chuẩn hoá NHẸ: bỏ dấu tiếng Việt, hạ chữ thường, gộp khoảng trắng — nhưng

    GIỮ dấu câu.

    Cần một dạng thứ hai vì hai dấu hiệu neo vào chính dấu hai chấm: `Đơn vị: …`
    là nhãn ô trong tờ mẫu, còn "đơn vị tính trong hợp đồng" là tiếng Việt bình
    thường và phải cho qua. Gộp hết dấu câu như `_gap` thì hai thứ đó thành một,
    và cổng loại oan mọi tiêu đề có chữ "đơn vị".
    """
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"\s+", " ", fold_dau(s).lower()).strip()


#: Dấu hiệu tiêu đề bị lấy thẳng từ ruột tờ mẫu, so trên chuỗi đã qua `_gap`.
#: Danh sách này phải bám sát cổng bên xuất bản — lỏng hơn thì bài bị loại ở đó
#: sau khi đã tốn tiền sinh, chặt hơn thì loại oan bài viết đúng.
_DAU_HIEU_RUOT_MAU: tuple[tuple[str, re.Pattern], ...] = (
    ("quốc hiệu", re.compile(r"\bcong hoa (xa hoi )?(chu nghia )?viet nam\b")),
    ("tiêu ngữ", re.compile(r"\bdoc lap tu do\b")),
    ("mẫu số", re.compile(r"\bmau so\b")),
    ("phụ lục", re.compile(r"\bphu luc\b")),
    ("biểu mẫu số", re.compile(r"\bbieu mau so\b")),
    ("tên cơ quan/đơn vị", re.compile(r"\bten co quan\b")),
)

#: Dấu hiệu neo vào dấu hai chấm, so trên chuỗi đã qua `_giu_dau_cau`.
_DAU_HIEU_CO_DAU_CAU: tuple[tuple[str, re.Pattern], ...] = (
    ("đơn vị:", re.compile(r"\bdon vi\s*:")),
    ("tên cơ quan/đơn vị:", re.compile(r"\bten co quan\s*[/:]")),
)


@dataclass
class KetQuaCong:
    """Kết quả một cổng: đạt hay không, và vì sao không."""

    dat: bool
    ly_do: str = ""

    def __bool__(self) -> bool:
        return self.dat


def chuoi_hop_le(gia_tri) -> str | None:
    """Ép về chuỗi, hoặc None nếu đầu vào không phải chuỗi.

    Đầu ra mô hình là JSON tuỳ ý: `"tieu_de": 123`, `"than_bai": ["a","b"]`,
    `"mo_ta": null` đều là JSON hợp lệ. Gọi thẳng `.strip()` lên chúng ném
    AttributeError — mà AttributeError KHÔNG phải SinhThatBai, nên nó thoát khỏi
    mọi lớp bắt lỗi của bên gọi, giết cả lượt chạy và vứt luôn những bài đã sinh
    thành công trước đó. Một bản ghi méo phải làm hỏng đúng một biểu mẫu.
    """
    if gia_tri is None:
        return ""
    return gia_tri if isinstance(gia_tri, str) else None


def cong_tieu_de(tieu_de) -> KetQuaCong:
    """Từ chối tiêu đề mang dấu hiệu lấy từ ruột tờ mẫu.

    Đây là bản sao chủ động của cổng bên xuất bản. Nó nhân bản một quy tắc — có
    giá — nhưng đổi lại phát hiện được lỗi ở đúng chỗ sinh ra lỗi, nơi còn sinh
    lại được. Danh sách dấu hiệu nằm ngay trên, và mẫu prompt §5 nói lại cùng
    những dấu hiệu đó cho mô hình.
    """
    tho = chuoi_hop_le(tieu_de)
    if tho is None:
        return KetQuaCong(False, f"tiêu đề không phải chuỗi ({type(tieu_de).__name__})")
    goc = tho.strip()
    if len(goc) < TIEU_DE_MIN:
        return KetQuaCong(False, f"tiêu đề ngắn hơn {TIEU_DE_MIN} ký tự")
    if len(goc) > TIEU_DE_MAX:
        return KetQuaCong(False, f"tiêu đề dài {len(goc)} ký tự, trần {TIEU_DE_MAX}")

    phang = _gap(goc)
    for ten, mau in _DAU_HIEU_RUOT_MAU:
        if mau.search(phang):
            return KetQuaCong(False, f"tiêu đề mang dấu hiệu ruột tờ mẫu: {ten}")

    co_dau = _giu_dau_cau(goc)
    for ten, mau in _DAU_HIEU_CO_DAU_CAU:
        if mau.search(co_dau):
            return KetQuaCong(False, f"tiêu đề mang dấu hiệu ruột tờ mẫu: {ten}")
    return KetQuaCong(True)


def cong_hop_dong(ban_ghi: dict) -> KetQuaCong:
    """Kiểm bản ghi có đúng §1 hợp đồng trước khi ghi ra file.

    Kiểm ở đây chứ không tin bên nhận kiểm hộ: bên nhận bỏ bản ghi hỏng và báo,
    nhưng lúc đó file đã giao đi và người vận hành phải chạy lại cả lượt.
    """
    khoa = chuoi_hop_le(ban_ghi.get("form_key"))
    if khoa is None:
        return KetQuaCong(False, "form_key không phải chuỗi")
    if not khoa.strip():
        return KetQuaCong(False, "thiếu form_key")

    kq = cong_tieu_de(ban_ghi.get("tieu_de"))
    if not kq:
        return kq

    mo_ta = chuoi_hop_le(ban_ghi.get("mo_ta"))
    if mo_ta is None:
        return KetQuaCong(False, "mo_ta không phải chuỗi")
    mo_ta = mo_ta.strip()
    if len(mo_ta) > MO_TA_MAX:
        return KetQuaCong(False, f"mo_ta dài {len(mo_ta)} ký tự, trần {MO_TA_MAX}")

    than_bai = chuoi_hop_le(ban_ghi.get("than_bai"))
    if than_bai is None:
        return KetQuaCong(False, "than_bai không phải chuỗi")
    if not than_bai.strip():
        return KetQuaCong(False, "thân bài rỗng")
    if len(than_bai) > THAN_BAI_MAX:
        return KetQuaCong(
            False, f"thân bài dài {len(than_bai)} ký tự, trần {THAN_BAI_MAX}"
        )

    if ban_ghi.get("citation_ok") is not True:
        return KetQuaCong(False, "citation_ok không phải true")
    return KetQuaCong(True)


@dataclass
class NguonTrichDan:
    """Nhóm số hiệu ĐƯỢC NGUỒN BẢO CHỨNG cho một bài.

    Dựng TỪ NGUỒN mô hình được đọc — căn cứ trong kho, toàn văn văn bản căn cứ,
    ruột tờ mẫu — và **không bao giờ** từ đầu ra của mô hình. Docstring của
    src/rag/citation_check.py nói thẳng: bên gọi dựng nhóm này từ đầu ra mô hình
    thì cổng tự vô hiệu hoá, vì lúc đó mọi số bịa đều tự bảo chứng cho chính nó.
    """

    so_hieu: set[str] = field(default_factory=set)

    def them_van_ban(self, text: str) -> None:
        """Nạp mọi số hiệu xuất hiện trong một khối văn bản NGUỒN."""
        self.so_hieu.update(extract_doc_nums(text or ""))

    def them_so_hieu(self, ds) -> None:
        self.so_hieu.update(s for s in ds if s)


def van_ban_doi_chieu(tieu_de: str = "", mo_ta: str = "", than_bai: str = "") -> str:
    """Gộp MỌI trường văn bản của bản ghi để đem đi đối chiếu trích dẫn.

    VÌ SAO KHÔNG CHỈ SOI `than_bai`: cả ba trường đều được đăng lên trang public.
    `tieu_de` thành thẻ `<title>` và `<h1>`, `mo_ta` thành meta description —
    tức là thứ hiện ra trên kết quả tìm kiếm của Google. Một số hiệu bịa nằm ở đó
    còn dễ thấy hơn nằm giữa thân bài, mà nếu cổng chỉ soi thân bài thì bản ghi
    ấy vẫn được đóng dấu `citation_ok: true` và đi thẳng sang bên xuất bản.
    """
    return "\n".join(t for t in (tieu_de, mo_ta, than_bai) if t)


def cong_trich_dan(
    van_ban: str,
    nguon: NguonTrichDan,
    db_path: Path | None = None,
) -> tuple[bool, CitationReport]:
    """Chạy cổng đối chiếu trích dẫn, trả về (đạt, báo cáo chi tiết).

    `van_ban` phải là TOÀN BỘ phần chữ của bản ghi — dựng bằng
    `van_ban_doi_chieu(tieu_de, mo_ta, than_bai)`, không phải riêng thân bài.

    MẶC ĐỊNH TỪ CHỐI. Bên xuất bản phân biệt ba trạng thái: `true` nhận, `false`
    loại vĩnh viễn, THIẾU CỜ cũng loại — vì thiếu cờ nghĩa là cổng CHƯA CHẠY,
    không phải "đã qua". Nên hàm này luôn trả về một giá trị boolean thật; bên
    gọi không được để trống trường `citation_ok`.
    """
    try:
        bao_cao = check_citations(van_ban, db_path=db_path,
                                  extra_allowed=nguon.so_hieu)
    except sqlite3.Error as e:
        # Kho đối chiếu không mở được thì cổng KHÔNG chạy được, và cổng không
        # chạy được nghĩa là không bài nào được đóng dấu — chứ không phải mọi
        # bài đều qua. Ném lỗi có tên riêng để bên gọi dừng cả lượt một cách
        # tường minh, thay vì để OperationalError thô làm vỡ giữa chừng và vứt
        # luôn những bài đã sinh xong.
        raise KhoDoiChieuHong(
            f"không mở được kho đối chiếu trích dẫn ({db_path}): {e}"
        ) from e
    return bao_cao.ok, bao_cao


__all__ = [
    "TIEU_DE_MIN", "TIEU_DE_MAX", "MO_TA_MAX", "THAN_BAI_MAX",
    "KetQuaCong", "NguonTrichDan", "KhoDoiChieuHong", "chuoi_hop_le",
    "cong_tieu_de", "cong_hop_dong", "cong_trich_dan", "van_ban_doi_chieu",
]
