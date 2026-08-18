"""
Bóc dữ liệu biểu mẫu từ HTML đã lưu — thuần hàm, KHÔNG chạm mạng.

Tách khỏi src/sources/tvpl_forms.py có chủ đích: phần cào phải qua Chrome thật vì
Cloudflare chặn mọi thứ khác, mà một module chỉ chạy được khi có trình duyệt thì
không test được. Ở đây chỉ có HTML vào — dữ liệu ra, nên test chạy trên fixture
lưu sẵn ở tests/fixtures/forms/ và bắt được ngay khi TVPL đổi markup.

HAI KHO, HAI DẠNG TRANG:

  /bieumau/{id}/{slug}   ruột mẫu trong `.divNoiDungBM`
                         có khối "Cập nhật: …" + "Căn cứ: <a>…</a>" ngay dưới
                         thanh breadcrumb

  /hopdong/{id}/{slug}   ruột mẫu trong `div.divTNPL > div` (KHÔNG có
                         `.divNoiDungBM`), và KHÔNG có trường "Căn cứ" — căn cứ
                         nằm ngay trong lời văn hợp đồng ("Căn cứ Bộ luật Dân sự
                         năm 2015 số 91/2015/QH13…"), thường 2–4 cái

Trang liệt kê thì hai kho dùng chung một khuôn: mỗi mục là một `p.nqTitle` nằm
trong khối bọc vẽ sọc xen kẽ `content-0` / `content-1` — xem `tach_danh_sach()`.

Fixture lưu dạng .html.gz: bốn trang thật cộng lại 1,1 MB thô mà nén còn ~7%, và
cắt bớt cho nhẹ thì fixture hết còn là bản sao trung thực nên không bắt được TVPL
đổi markup ở phần đã cắt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from bs4 import BeautifulSoup

#: Ruột mẫu ngắn hơn ngưỡng này coi như trang hỏng, KHÔNG phải biểu mẫu ngắn.
#: Mẫu ngắn nhất đo được trên kho thật là 7.608 ký tự HTML; 200 là ngưỡng chỉ
#: chạm tới khi trang trả về vỏ rỗng. Không có chốt này thì TVPL đổi tên class là
#: cả kho lặng lẽ đầy biểu mẫu trắng, và không ai biết cho tới lúc khách mở file.
MIN_BODY_CHARS = 200

SOURCE_BIEU_MAU = "bieumau"
SOURCE_HOP_DONG = "hopdong"

#: Căn cứ lấy từ trường riêng của trang (chắc) hay bóc từ lời văn (kém chắc hơn).
REF_TRUONG_CAN_CU = "truong_can_cu"
REF_TRONG_RUOT_MAU = "trong_ruot_mau"

_RE_TIM_THAY = re.compile(r"Tìm thấy\s*([\d.,]+)\s*(?:biểu\s*)?mẫu", re.IGNORECASE)
_RE_NGAY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_RE_CAP_NHAT = re.compile(r"Cập\s*nhật:\s*(\d{1,2}/\d{1,2}/\d{4})")
_RE_URL_ITEM = re.compile(r"^/(bieumau|hopdong)/(\d+)/([^/?#]*)")
#: Khối bọc một dòng trên trang liệt kê. TVPL vẽ sọc xen kẽ nên có hai lớp.
_RE_LOP_DONG = re.compile(r"^content-\d+$")
#: Nhãn căn cứ TVPL viết kèm loại văn bản: "Thông tư 131/2025/TT-BTC".
#: Cột documents.doc_num chỉ chứa phần số hiệu, nên phải cắt tiền tố mới khớp.
_RE_TIEN_TO_LOAI = re.compile(
    r"^(?:Bộ\s+luật|Luật|Pháp\s+lệnh|Hiến\s+pháp|Nghị\s+quyết(?:\s+liên\s+tịch)?|"
    r"Nghị\s+định|Quyết\s+định|Chỉ\s+thị|Thông\s+tư(?:\s+liên\s+tịch)?|"
    r"Công\s+văn|Thông\s+báo|Kế\s+hoạch|Hướng\s+dẫn|Lệnh|Sắc\s+lệnh)\s+",
    re.IGNORECASE,
)
#: id văn bản TVPL nằm ở cụm số cuối slug: …-Che-do-bao-cao-686963.aspx
_RE_TVPL_DOC_ID = re.compile(r"-(\d+)\.aspx", re.IGNORECASE)

#: Số hiệu văn bản trong lời văn hợp đồng. Cố ý HẸP hơn bộ nhận dạng của
#: src/rag/citation_check.py: ở đây đầu vào là lời văn tự do đầy số điện thoại,
#: mã số thuế, số nhà — nên bắt buộc phải có phần "/NĂM/" ở giữa.
_RE_SO_HIEU = re.compile(
    r"\b(\d{1,4}[A-ZĐ]?/(?:19|20)\d{2}/[A-ZĐ][A-ZĐ0-9\-]{1,14})\b"
)


class FormParseError(ValueError):
    """HTML không bóc được thành biểu mẫu dùng được."""


@dataclass
class FormListItem:
    """Một dòng trên trang liệt kê.

    `field_code` và `form_type_code` KHÔNG có trên trang: mục liệt kê chỉ hiện
    tiêu đề, từ khoá và ngày cập nhật. Chúng đến từ chính bộ lọc đã dùng để mở
    trang, nên bên cào điền vào — xem TVPLFormCrawler.duyet_danh_sach().
    """

    source: str
    external_id: str
    slug: str
    title: str
    url: str
    keywords: list[str] = field(default_factory=list)
    updated_on: date | None = None
    field_code: int | None = None
    form_type_code: int | None = None

    @property
    def form_key(self) -> str:
        return f"{self.source}-{self.external_id}"


@dataclass
class FormRef:
    """Một căn cứ pháp lý của biểu mẫu.

    `doc_num` là số hiệu TRẦN ("131/2025/TT-BTC") để khớp được với cột
    documents.doc_num; `nhan` giữ nguyên cách TVPL viết ("Thông tư
    131/2025/TT-BTC") để hiện lại cho người đọc. Gộp hai thứ vào một cột thì
    hoặc mất chỗ khớp, hoặc mất chỗ hiển thị.
    """

    doc_num: str
    nhan: str = ""
    url: str | None = None
    tvpl_doc_id: str | None = None
    source: str = REF_TRUONG_CAN_CU


def chuan_hoa_so_hieu(nhan: str) -> str:
    """Cắt tiền tố loại văn bản khỏi nhãn căn cứ. "Luật Doanh nghiệp" → nguyên văn.

    Chỉ cắt khi phần còn lại vẫn là số hiệu nhận ra được. Nhãn dạng thuần chữ
    ("Bộ luật Dân sự") không có số hiệu để cắt, giữ nguyên còn hơn cắt cụt thành
    "Dân sự" rồi đem đi khớp với kho.
    """
    goc = _gon(nhan)
    cat = _gon(_RE_TIEN_TO_LOAI.sub("", goc))
    return cat if "/" in cat else goc


@dataclass
class FormDetail:
    """Trang chi tiết một biểu mẫu."""

    source: str
    external_id: str
    title: str
    body_html: str
    updated_on: date | None = None
    refs: list[FormRef] = field(default_factory=list)


# ──────────────────────────────────────────────
# Tiện ích
# ──────────────────────────────────────────────
def _soup(html: str) -> BeautifulSoup:
    # "html.parser" chứ không phải "lxml": lxml không nằm trong danh sách phụ
    # thuộc khai báo, có mặt trong venv chỉ vì gói khác kéo theo. Dựa vào nó là
    # dựa vào may mắn.
    return BeautifulSoup(html or "", "html.parser")


def _ngay(chuoi: str | None) -> date | None:
    """dd/mm/yyyy → date. Trả None thay vì đoán khi không đọc được.

    Ngày sai còn tệ hơn không có ngày: bộ đồng bộ dùng nó để quyết định biểu mẫu
    nào vừa đổi.
    """
    if not chuoi:
        return None
    m = _RE_NGAY.search(chuoi)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%d/%m/%Y").date()
    except ValueError:
        return None


def _gon(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


#: Thẻ kết thúc một dòng/khối. Chỉ những thẻ này mới được chèn ngắt dòng.
_THE_KHOI = ("br", "p", "div", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6")


def chu_trong_ruot(body_html: str) -> str:
    """Ruột mẫu ở dạng chữ trơn, đã gộp khoảng trắng.

    KHÔNG ĐƯỢC DÙNG `get_text(" ")`. Aspose xuất từ Word cắt chữ thành nhiều thẻ
    `<span>` liền nhau — có chỗ cắt giữa từ:

        <span>Độc lậ</span><span>p -</span><span> Tự</span>

    Ghép bằng dấu cách sẽ ra "Độc lậ p - Tự do", "Bộ l uật D ân sự", "T h ời hạn".
    Chữ vỡ như vậy làm bộ đếm từ khoá của phễu trượt hết ("bộ luật dân sự" không
    còn khớp), và bản DOCX dựng lại thì không đọc được. Đo trên fixture thật:
    riêng trang hợp đồng khoán việc có hàng chục chỗ bị chèn nhầm.

    Cách đúng: ghép các thẻ nội tuyến KHÔNG dấu phân cách, chỉ ngắt dòng ở thẻ
    khối. Ghép trắng trơn cũng sai theo chiều ngược lại — hai đoạn liền nhau sẽ
    dính thành "…VIỆT NAMĐộc lập…".
    """
    soup = _soup(body_html)
    for the in soup.find_all(_THE_KHOI):
        the.insert_after("\n")
    return _gon(soup.get_text(""))


def tach_so_luong(html: str) -> int | None:
    """Số "Tìm thấy N biểu mẫu" trên trang liệt kê. None nếu trang không có.

    Dùng để biết còn bao nhiêu trang phải lật, và để test khoá lại đúng dạng URL
    bộ lọc — xem docstring của src/sources/tvpl_forms.py.
    """
    m = _RE_TIM_THAY.search(_soup(html).get_text(" "))
    if not m:
        return None
    return int(m.group(1).replace(".", "").replace(",", ""))


# ──────────────────────────────────────────────
# Trang liệt kê
# ──────────────────────────────────────────────
def tach_danh_sach(html: str, base_url: str = "https://thuvienphapluat.vn") -> list[FormListItem]:
    """Bóc các mục trên một trang liệt kê của /bieumau hoặc /hopdong.

    ĐI TỪ TIÊU ĐỀ RA NGOÀI, KHÔNG ĐI TỪ KHỐI BỌC VÀO. Bản đầu chọn
    `div.content-1` rồi lấy tiêu đề bên trong, và lấy được đúng MỘT NỬA: TVPL vẽ
    các dòng đan xen hai lớp sọc `content-1` / `content-0`, nên 20 mẫu mỗi trang
    chỉ ra 10. Mất một nửa kho mà không có lỗi nào nổi lên — kiểu hỏng tệ nhất.
    `p.nqTitle` thì mục nào cũng có, không phụ thuộc sọc chẵn lẻ.

    Nhận diện kho từ chính đường dẫn của mục chứ không từ tham số truyền vào:
    trang /bieumau có lẫn khối "XEM NHIỀU NHẤT" ở cột phải, đường dẫn là thứ duy
    nhất phân biệt được.
    """
    items: list[FormListItem] = []
    seen: set[str] = set()

    for a in _soup(html).select("p.nqTitle > a"):
        block = a.find_parent("div", class_=_RE_LOP_DONG) or a.find_parent("div")
        if block is None:
            continue
        href = a.get("href") or ""
        m = _RE_URL_ITEM.match(href)
        if not m:
            continue
        source, external_id, slug = m.group(1), m.group(2), m.group(3)
        key = f"{source}-{external_id}"
        if key in seen:
            continue
        seen.add(key)

        keywords = [
            _gon(k.get_text())
            for k in block.select("p.links-bot a")
            if _gon(k.get_text())
        ]
        items.append(FormListItem(
            source=source,
            external_id=external_id,
            slug=slug,
            title=_gon(a.get_text()),
            url=f"{base_url}{href}",
            keywords=keywords,
            updated_on=_ngay(_gon(block.select_one("div.right-col").get_text())
                             if block.select_one("div.right-col") else None),
        ))

    return items


def co_trang_sau(html: str) -> bool:
    """Trang liệt kê còn trang kế tiếp không."""
    return any(
        "trang sau" in _gon(a.get_text()).lower()
        for a in _soup(html).select("a")
    )


# ──────────────────────────────────────────────
# Trang chi tiết
# ──────────────────────────────────────────────
def _khoi_meta(soup: BeautifulSoup):
    """Thẻ <span> chứa "Cập nhật: …" và "Căn cứ: …" trên trang chi tiết.

    Bám vào nội dung chữ chứ không vào thuộc tính style: style là chuỗi CSS nội
    tuyến mà TVPL đổi thường xuyên, còn hai nhãn tiếng Việt kia thì không.
    """
    for span in soup.select("p > span"):
        if "Cập nhật:" in span.get_text():
            return span
    return None


def _tach_body(soup: BeautifulSoup) -> str:
    """Ruột biểu mẫu, thử /bieumau trước rồi mới tới /hopdong.

    `.divNoiDungBM` chỉ có ở /bieumau. /hopdong đặt ruột hợp đồng trong một
    <div> không lớp nằm ngay trong `.divTNPL`, nên phải lấy con trực tiếp đầu
    tiên có nội dung thay vì lấy cả `.divTNPL` (kéo theo cả thanh chia sẻ, quảng
    cáo và khối "XEM NHIỀU NHẤT").
    """
    bm = soup.select_one(".divNoiDungBM")
    if bm is not None:
        return bm.decode_contents()

    tnpl = soup.select_one("div.divTNPL")
    if tnpl is not None:
        for con in tnpl.find_all("div", recursive=False):
            if len(_gon(con.get_text())) >= MIN_BODY_CHARS:
                return con.decode_contents()
        return tnpl.decode_contents()

    return ""


def _tach_refs_tu_truong(span, base_url: str) -> list[FormRef]:
    """Căn cứ từ trường riêng của /bieumau — đường chắc chắn nhất.

    Thẻ <a> ở đây trỏ thẳng sang trang văn bản kèm id TVPL trong slug
    (…-686963.aspx). Id đó khớp được với documents.tvpl_id, chính xác hơn nhiều
    so với dò theo số hiệu: số hiệu không duy nhất toàn quốc (63 tỉnh đánh số
    độc lập), id TVPL thì duy nhất.
    """
    if span is None:
        return []
    refs: list[FormRef] = []
    for a in span.select("a[href]"):
        href = a.get("href") or ""
        if "/van-ban/" not in href:
            continue
        nhan = _gon(a.get_text())
        if not nhan:
            continue
        m = _RE_TVPL_DOC_ID.search(href)
        refs.append(FormRef(
            doc_num=chuan_hoa_so_hieu(nhan),
            nhan=nhan,
            url=href if href.startswith("http") else f"{base_url}{href}",
            tvpl_doc_id=m.group(1) if m else None,
            source=REF_TRUONG_CAN_CU,
        ))
    return refs


def tach_can_cu_trong_ruot(body_text: str, gioi_han: int = 8) -> list[FormRef]:
    """Số hiệu văn bản nêu trong lời văn — đường duy nhất cho /hopdong.

    Chỉ quét phần ĐẦU của lời văn: khối "Căn cứ …" luôn nằm ngay dưới quốc hiệu,
    còn phần thân hợp đồng có chỗ điền đầy số (mã số thuế, số tài khoản, số điện
    thoại) dễ khớp nhầm. `gioi_han` chặn trường hợp một mẫu liệt kê hàng chục
    văn bản làm phình bảng refs.
    """
    dau = (body_text or "")[:4000]
    out: list[FormRef] = []
    for so_hieu in _RE_SO_HIEU.findall(dau):
        if any(r.doc_num == so_hieu for r in out):
            continue
        out.append(FormRef(doc_num=so_hieu, nhan=so_hieu, source=REF_TRONG_RUOT_MAU))
        if len(out) >= gioi_han:
            break
    return out


def tach_chi_tiet(
    html: str,
    source: str,
    external_id: str,
    base_url: str = "https://thuvienphapluat.vn",
) -> FormDetail:
    """Bóc trang chi tiết. NÉM FormParseError khi ruột mẫu rỗng hoặc quá ngắn.

    Ném chứ không trả về bản ghi rỗng: biểu mẫu không có ruột thì vô dụng với
    người dùng, mà lưu im lặng lại làm cả kho trông như đã cào xong. Bên gọi bắt
    lỗi này và ghi crawl_status='EMPTY_BODY' để người vận hành thấy được.
    """
    soup = _soup(html)

    span = _khoi_meta(soup)
    tieu_de = ""
    for p in soup.select("p"):
        txt = p.get_text()
        if "=>" in txt and ("Biểu mẫu" in txt or "Mẫu hợp đồng" in txt):
            manh = p.select_one("span")
            tieu_de = _gon(manh.get_text()) if manh else ""
            break
    if not tieu_de and soup.title:
        tieu_de = _gon(soup.title.get_text())

    body_html = _tach_body(soup)
    body_text = chu_trong_ruot(body_html)
    if len(body_text) < MIN_BODY_CHARS:
        raise FormParseError(
            f"Ruột biểu mẫu {source}-{external_id} chỉ có {len(body_text)} ký tự "
            f"(tối thiểu {MIN_BODY_CHARS}). Nhiều khả năng TVPL đổi markup hoặc "
            f"trang trả về vỏ rỗng — KHÔNG lưu bản ghi trắng."
        )

    refs = _tach_refs_tu_truong(span, base_url)
    if not refs:
        refs = tach_can_cu_trong_ruot(body_text)

    return FormDetail(
        source=source,
        external_id=external_id,
        title=tieu_de,
        body_html=body_html,
        updated_on=_ngay(
            _RE_CAP_NHAT.search(span.get_text()).group(1)
            if span and _RE_CAP_NHAT.search(span.get_text())
            else None
        ),
        refs=refs,
    )


__all__ = [
    "MIN_BODY_CHARS", "SOURCE_BIEU_MAU", "SOURCE_HOP_DONG",
    "REF_TRUONG_CAN_CU", "REF_TRONG_RUOT_MAU",
    "FormParseError", "FormListItem", "FormRef", "FormDetail",
    "tach_so_luong", "tach_danh_sach", "co_trang_sau",
    "tach_chi_tiet", "tach_can_cu_trong_ruot", "chuan_hoa_so_hieu",
    "chu_trong_ruot",
]
