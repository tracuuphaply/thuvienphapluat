"""
Kết xuất báo cáo pháp lý ra PDF theo bố cục dành cho ấn phẩm gửi khách.

Khác với `pdf_exporter` (bản gọn dùng cho bot Telegram), module này dựng trang
bìa, đầu/chân trang chạy suốt, khối FIGURE có chú thích nguồn và hộp nhận định —
theo mẫu báo cáo nghiên cứu của Thomson Reuters Institute.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, Image, KeepTogether, NextPageTemplate,
    PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from src.utils.report_theme import (
    BRAND, BRAND_DEEP, BRAND_SOFT, CREAM, DARK_GREEN, Figure, INK, INK_SOFT,
    ON_BRAND, ORANGE, RULE, SURFACE, TINT,
)

FONT = "RptSans"
FONT_B = "RptSans-Bold"
FONT_I = "RptSans-Italic"

_PAGE_W, _PAGE_H = A4
_MARGIN = 54
_CONTENT_W = _PAGE_W - 2 * _MARGIN


# Bộ font ứng viên, xếp theo thứ tự ưu tiên. Mỗi mục là (thường, đậm, nghiêng).
#
# BẮT BUỘC phủ được chữ Việt có dấu. Font mặc định của ReportLab (Helvetica) chỉ
# có Latin-1 nên "Nghị định" ra "Ngh nh" — mất chữ mà không báo lỗi, đúng kiểu
# hỏng tệ nhất với một báo cáo pháp lý.
_UNG_VIEN: tuple[tuple[str, str, str], ...] = (
    # macOS
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
    # Windows
    (r"C:\Windows\Fonts\arial.ttf",
     r"C:\Windows\Fonts\arialbd.ttf",
     r"C:\Windows\Fonts\ariali.ttf"),
    (r"C:\Windows\Fonts\segoeui.ttf",
     r"C:\Windows\Fonts\segoeuib.ttf",
     r"C:\Windows\Fonts\segoeuii.ttf"),
    # Linux — DejaVu có trong hầu hết bản phân phối và phủ đủ chữ Việt
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
)


class FontKhongTimThay(RuntimeError):
    """Không có font nào phủ được chữ Việt trên máy này."""


def _bo_font_dung_duoc() -> tuple[str, str, str] | None:
    for bo in _UNG_VIEN:
        if Path(bo[0]).exists():
            # Thiếu bản đậm/nghiêng thì dùng bản thường thay — xấu hơn nhưng
            # vẫn đọc được, còn hơn không dựng được PDF.
            return tuple(p if Path(p).exists() else bo[0] for p in bo)  # type: ignore[return-value]
    return None


_da_dang_ky = False


def _register_fonts() -> None:
    """Đăng ký font, gọi lúc DỰNG chứ không lúc import.

    Bản trước hardcode đường dẫn macOS và gọi ngay ở cấp module — nhánh dự phòng
    cũng trỏ vào chính đường dẫn đó, nên trên Windows/Linux cả hai lần đều hỏng
    và lỗi thoát ra khỏi hàm. Hệ quả không phải "PDF hỏng" mà là `import
    report_pdf` chết, kéo theo mọi thứ import nó — kể cả những đường không dựng
    PDF.
    """
    global _da_dang_ky
    if _da_dang_ky:
        return

    bo = _bo_font_dung_duoc()
    if not bo:
        raise FontKhongTimThay(
            "Không tìm thấy font phủ chữ Việt. Đã thử: "
            + ", ".join(b[0] for b in _UNG_VIEN)
            + ". Cài một trong số đó (Linux: apt install fonts-dejavu-core) "
            "hoặc đặt đường dẫn khác vào src/utils/report_pdf.py:_UNG_VIEN."
        )

    for ten, duong_dan in zip((FONT, FONT_B, FONT_I), bo):
        pdfmetrics.registerFont(TTFont(ten, duong_dan))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_B, italic=FONT_I)
    _da_dang_ky = True


DEFAULT_LOGO = Path(__file__).resolve().parents[2] / "assets" / "logo_thongtincty.png"


@dataclass
class ReportMeta:
    industry: str
    period: str
    cutoff: str
    industry_code: str = ""
    industry_official: str = ""
    scope: str = ""
    company: str = ""
    contact: str = ""
    figures: list[Figure] = field(default_factory=list)
    logo_path: Path | None = None
    # Lời ngỏ hợp tác ở chân trang. Để trống thì chân trang lùi về dạng gọn
    # (chỉ tên đơn vị + số trang), nên bật/tắt được mà không phải sửa code.
    partner_title: str = ""
    partner_pitch: str = ""
    partner_cta: str = ""
    partner_contact: str = ""
    partner_col1_title: str = ""
    partner_col1: list[str] = field(default_factory=list)
    partner_col2_title: str = ""
    partner_col2: list[str] = field(default_factory=list)

    def anh_hop_tac(self) -> Path | None:
        p = Path(__file__).resolve().parents[2] / "assets" / "bat_tay_xanh.png"
        return p if p.exists() else None

    def logo(self) -> Path | None:
        path = self.logo_path or DEFAULT_LOGO
        return path if Path(path).exists() else None


# ── Styles ───────────────────────────────────────────────────────────────────
def _styles() -> dict[str, ParagraphStyle]:
    return {
        "h1": ParagraphStyle(
            "h1", fontName=FONT_B, fontSize=19, leading=23, textColor=colors.HexColor(ORANGE),
            spaceBefore=20, spaceAfter=10, keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "h2", fontName=FONT_B, fontSize=12.5, leading=16,
            textColor=colors.HexColor(DARK_GREEN), spaceBefore=14, spaceAfter=6,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "h3", fontName=FONT_B, fontSize=10, leading=13.5,
            textColor=colors.HexColor(INK), spaceBefore=10, spaceAfter=4,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body", fontName=FONT, fontSize=9.5, leading=14.5,
            textColor=colors.HexColor(INK), spaceAfter=7,
        ),
        "bullet": ParagraphStyle(
            "bullet", fontName=FONT, fontSize=9.5, leading=14,
            textColor=colors.HexColor(INK), leftIndent=14, firstLineIndent=-9,
            spaceAfter=4,
        ),
        "fig_num": ParagraphStyle(
            "fig_num", fontName=FONT_B, fontSize=7.5, leading=10,
            textColor=colors.HexColor(INK), spaceAfter=1,
        ),
        "fig_title": ParagraphStyle(
            "fig_title", fontName=FONT_B, fontSize=12, leading=15,
            textColor=colors.HexColor(ORANGE), spaceAfter=6,
        ),
        "source": ParagraphStyle(
            "source", fontName=FONT_I, fontSize=7.5, leading=10,
            textColor=colors.HexColor(INK_SOFT), alignment=2, spaceBefore=3,
        ),
        "callout_h": ParagraphStyle(
            "callout_h", fontName=FONT_B, fontSize=10, leading=13,
            textColor=colors.white,
        ),
        "callout": ParagraphStyle(
            "callout", fontName=FONT, fontSize=9.5, leading=14.5,
            textColor=colors.HexColor(INK), spaceAfter=6,
        ),
        "cell": ParagraphStyle(
            "cell", fontName=FONT, fontSize=8, leading=11,
            textColor=colors.HexColor(INK),
        ),
        "cell_h": ParagraphStyle(
            "cell_h", fontName=FONT_B, fontSize=8, leading=11, textColor=colors.white,
        ),
    }


# ── Trang bìa và đầu/chân trang ──────────────────────────────────────────────
class _Canvas(rl_canvas.Canvas):
    def __init__(self, *args, meta: ReportMeta, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta = meta
        self._states: list[dict] = []

    def showPage(self):
        self._states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._states)
        for state in self._states:
            self.__dict__.update(state)
            if self._pageNumber > 1:
                self._chrome(total)
            rl_canvas.Canvas.showPage(self)
        rl_canvas.Canvas.save(self)

    def _chrome(self, total: int) -> None:
        """Đầu và chân trang chạy suốt, giống mẫu tham chiếu."""
        self.saveState()
        self.setFont(FONT, 7.5)
        self.setFillColor(colors.HexColor(INK_SOFT))

        logo = self._meta.logo()
        x = _MARGIN
        if logo:
            self.drawImage(str(logo), _MARGIN, _PAGE_H - 46, width=13, height=13,
                           mask="auto", preserveAspectRatio=True)
            x = _MARGIN + 18

        head = f"Báo cáo pháp lý ngành {self._meta.industry} · {self._meta.period}"
        self.drawString(x, _PAGE_H - 40, head[:92])
        self.drawRightString(_PAGE_W - _MARGIN, _PAGE_H - 40, str(self._pageNumber))
        self.setStrokeColor(colors.HexColor(RULE))
        self.setLineWidth(0.5)
        self.line(_MARGIN, _PAGE_H - 48, _PAGE_W - _MARGIN, _PAGE_H - 48)

        self._chan_trang()
        self.restoreState()

    def _chan_trang(self) -> None:
        """Chân trang mọi trang — một dòng liên hệ, không hơn."""
        # Chân trang MỌI TRANG chỉ là một dòng gọn. Khối thư ngỏ hợp tác là một
        # khối lớn chiếm gần một phần ba trang, in ở CUỐI báo cáo — lặp nó trên
        # cả chục trang thì báo cáo thành tờ rơi.
        foot = self._meta.contact or self._meta.company or ""
        if foot:
            self.drawString(_MARGIN, 30, foot[:110])
        return



def _ngat_dong(text: str, rong: float, font: str, co: float,
               toi_da: int = 2) -> list[str]:
    """Ngắt chuỗi thành tối đa `toi_da` dòng vừa bề ngang.

    Đo bằng stringWidth chứ không đếm ký tự: chữ Việt có dấu và chữ hoa rộng
    khác nhau đáng kể, cắt theo số ký tự thì lúc hụt lúc tràn ra ngoài dải màu.

    Ngắt theo TỪ. Bản trước cắt giữa từ và thêm ba chấm, nên lời chào mời hiện
    ra thành nửa câu cụt — với một khối quảng bá thì đó là hỏng hẳn, không phải
    xấu đi một chút.
    """
    tu = text.split()
    dong: list[str] = []
    hien = ""
    for t in tu:
        thu = f"{hien} {t}".strip()
        if pdfmetrics.stringWidth(thu, font, co) <= rong:
            hien = thu
            continue
        if hien:
            dong.append(hien)
        hien = t
        if len(dong) == toi_da:
            break
    if hien and len(dong) < toi_da:
        dong.append(hien)

    # Còn chữ chưa đặt được thì báo bằng ba chấm ở cuối dòng chót, chứ không
    # lặng lẽ nuốt mất.
    da_dat = " ".join(dong)
    if len(da_dat.split()) < len(tu) and dong:
        chot = dong[-1]
        while chot and pdfmetrics.stringWidth(chot + "…", font, co) > rong:
            chot = chot[:-1]
        dong[-1] = chot.rstrip() + "…"
    return dong


class KhoiThuNgo(Flowable):
    """Khối thư ngỏ hợp tác, in ở cuối báo cáo.

    Lấy bố cục từ banner mẫu người dùng gửi: logo góc trên trái, dải tiêu đề
    đậm vát chéo, hai cột liệt kê giá trị, nút gọi hành động, ảnh bên phải.

    VẼ BẰNG VECTOR, chỉ ảnh là raster. Các mảng màu và góc vát của banner gốc
    là ảnh bitmap; kéo chúng ngang khổ A4 sẽ rỗ khi in. Ảnh bắt tay đã đổi sang
    tone xanh hai màu (assets/bat_tay_xanh.png) để không chọi với xanh #003CA7
    dùng cho bìa, đầu bảng và biểu đồ — bản gốc màu cam.

    CHIỀU CAO TỰ TÍNH THEO NỘI DUNG. Bản đầu cố định 150pt, nên cột nào có mục
    dài phải xuống hai dòng là tràn ra ngoài khối và đè lên dòng liên hệ. Số
    dòng chỉ biết được sau khi ngắt chữ, nên phải ngắt trước rồi mới biết cao
    bao nhiêu.

    Là Flowable chứ không vẽ thẳng lên canvas: như vậy nó tự xuống trang mới khi
    trang cuối không đủ chỗ, thay vì đè lên chữ.
    """

    # ĐO CHO MÀN HÌNH, KHÔNG CHO BẢN IN.
    #
    # Bản trước lấy tỷ lệ của banner mẫu làm chuẩn nên chữ trong cột bị ép
    # xuống 6,8pt — cỡ đó chỉ đọc được khi phóng to, mà PDF này người ta mở
    # bằng trình xem ở 100%. Nay lấy DANH MỤC NỘI DUNG làm chuẩn còn kích
    # thước thì theo mức đọc được: 8,5pt là ngưỡng dưới cho chữ thân trên màn
    # hình, ngang với chú thích bảng ở phần còn lại của báo cáo.
    #
    # Khối vì vậy cao hơn banner gốc. Không sao — nó nằm cuối báo cáo, và một
    # khối cao mà đọc được thì hơn một khối vừa khung mà phải phóng to.
    CO_MUC = 8.5          # cỡ chữ mục trong cột
    CAO_DONG = 11         # khoảng cách dòng trong một mục
    CACH_MUC = 5          # khoảng hở giữa hai mục
    CAO_DAU = 52          # logo + tên đơn vị
    CAO_DAI = 34          # dải tiêu đề
    CAO_CUOI = 42         # nút CTA và dòng liên hệ
    HO_TREN_COT = 18      # hở giữa dải tiêu đề và tiêu đề cột
    CAO_PHU_DE = 16       # dòng phụ đề dưới dải
    LE = 18               # lề trong của khối
    CAO_TIEU_DE_COT = 16

    def __init__(self, meta: ReportMeta, rong: float):
        super().__init__()
        self.meta = meta
        self.width = rong
        self.vat = 16
        self.w_anh = rong * 0.30
        self.x_anh = rong - self.w_anh
        self.rong_cot = (self.x_anh - self.LE * 2 - 10) / 2

        # Ngắt chữ TRƯỚC, vì chiều cao phụ thuộc số dòng thật.
        self.cot = [
            [(t, _ngat_dong(t, self.rong_cot - 14, FONT, self.CO_MUC, 2))
             for t in (muc or [])[:4]]
            for muc in (meta.partner_col1, meta.partner_col2)
        ]
        # Dùng ĐÚNG các hằng số mà draw() dùng. Bản trước dự trữ 14pt cho tiêu
        # đề cột trong khi lúc vẽ tiêu đề chiếm 16 + 13 = 29pt, nên mục cuối
        # cùng luôn thò xuống đè lên dòng liên hệ.
        cao_cot = max(
            (self.HO_TREN_COT + self.CAO_TIEU_DE_COT
             + sum(len(d) * self.CAO_DONG + self.CACH_MUC for _, d in c)
             for c in self.cot if c), default=0)
        # partner_pitch hiện thành phụ đề một dòng dưới dải tiêu đề. Bản trước
        # chỉ dùng nó làm công tắc bật/tắt nên câu chào mời không xuất hiện ở
        # đâu cả — người sửa report_branding.json sẽ tưởng mình gõ vào chỗ vô
        # dụng.
        self.phu_de = _ngat_dong((meta.partner_pitch or "").strip(),
                                 self.x_anh - self.LE * 2, FONT_I, 9, 1)
        cao_phu_de = self.CAO_PHU_DE if self.phu_de else 0
        self.height = (self.CAO_DAU + self.CAO_DAI + cao_phu_de
                       + cao_cot + self.CAO_CUOI)

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c, W, H, m = self.canv, self.width, self.height, self.meta
        vat, w_anh, x_anh = self.vat, self.w_anh, self.x_anh

        # ── Nền thẻ ──
        c.setFillColor(colors.HexColor(SURFACE))
        c.rect(0, 0, W, H, stroke=0, fill=1)

        # ── Ảnh bên phải, cắt vát mép trái ──
        anh = m.anh_hop_tac()
        if anh:
            c.saveState()
            p = c.beginPath()
            p.moveTo(x_anh + vat, 0)
            p.lineTo(W, 0)
            p.lineTo(W, H)
            p.lineTo(x_anh, H)
            p.close()
            c.clipPath(p, stroke=0)
            # PHỦ KHUNG, GIỮ TỶ LỆ. Kéo giãn cho vừa khung làm bàn tay méo —
            # thấy rõ khi khối cao lên còn ảnh thì vuông. Phóng theo cạnh thiếu
            # rồi để đường cắt xén phần thừa, giống background-size: cover.
            rong_khung = w_anh + vat * 2
            iw, ih = ImageReader(str(anh)).getSize()
            ty_le = max(rong_khung / iw, H / ih)
            w_ve, h_ve = iw * ty_le, ih * ty_le
            c.drawImage(str(anh),
                        x_anh - vat - (w_ve - rong_khung) / 2,
                        -(h_ve - H) / 2,
                        width=w_ve, height=h_ve, mask=None)
            c.restoreState()
        else:
            c.setFillColor(colors.HexColor(BRAND_SOFT))
            c.rect(x_anh, 0, w_anh, H, stroke=0, fill=1)

        # ── Logo và tên đơn vị ──
        x_chu = self.LE
        logo = m.logo()
        if logo:
            c.drawImage(str(logo), self.LE, H - 38, width=26, height=26,
                        mask="auto", preserveAspectRatio=True)
            x_chu = self.LE + 32
        c.setFillColor(colors.HexColor(BRAND_DEEP))
        c.setFont(FONT_B, 13.5)
        c.drawString(x_chu, H - 30, (m.company or "")[:30])

        # ── Dải tiêu đề đậm, vát mép phải ──
        y_dai = H - self.CAO_DAU - self.CAO_DAI
        c.setFillColor(colors.HexColor(BRAND_DEEP))
        d = c.beginPath()
        d.moveTo(0, y_dai)
        d.lineTo(x_anh - 6, y_dai)
        d.lineTo(x_anh - 6 + vat, y_dai + self.CAO_DAI)
        d.lineTo(0, y_dai + self.CAO_DAI)
        d.close()
        c.drawPath(d, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_B, 14.5)
        c.drawString(self.LE, y_dai + 11.5,
                     (m.partner_title or "THƯ NGỎ HỢP TÁC")[:44])

        # ── Phụ đề dưới dải ──
        y_moc = y_dai
        if self.phu_de:
            c.setFillColor(colors.HexColor(INK_SOFT))
            c.setFont(FONT_I, 9)
            c.drawString(self.LE, y_dai - 13, self.phu_de[0])
            y_moc -= self.CAO_PHU_DE

        # ── Hai cột giá trị ──
        tieu_de_cot = (m.partner_col1_title, m.partner_col2_title)
        for i, muc in enumerate(self.cot):
            if not muc:
                continue
            x = self.LE + i * (self.rong_cot + 10)
            y = y_moc - self.HO_TREN_COT
            c.setFillColor(colors.HexColor(BRAND))
            c.setFont(FONT_B, 9.5)
            c.drawString(x, y, (tieu_de_cot[i] or "")[:34])
            y -= self.CAO_TIEU_DE_COT
            for _, dong in muc:
                c.setFillColor(colors.HexColor(BRAND))
                c.circle(x + 3, y + 2.8, 2, stroke=0, fill=1)
                c.setFillColor(colors.HexColor(INK))
                c.setFont(FONT, self.CO_MUC)
                for k, phan in enumerate(dong):
                    c.drawString(x + 10, y - k * self.CAO_DONG, phan)
                y -= len(dong) * self.CAO_DONG + self.CACH_MUC

        # ── Nút gọi hành động, đè lên ảnh như banner mẫu ──
        cta = (m.partner_cta or "").strip()
        if cta:
            c.setFont(FONT_B, 9.5)
            w_nut = pdfmetrics.stringWidth(cta, FONT_B, 9.5) + 28
            x_nut = W - w_nut - 14
            c.setFillColor(colors.HexColor(BRAND))
            c.rect(x_nut, 15, w_nut, 25, stroke=0, fill=1)
            c.setFillColor(colors.white)
            c.drawCentredString(x_nut + w_nut / 2, 23, cta)

        # ── Dòng liên hệ, nằm trong vùng CAO_CUOI nên không đụng cột ──
        lien_he = (m.partner_contact or "").strip()
        if lien_he:
            c.setFillColor(colors.HexColor(INK_SOFT))
            c.setFont(FONT, 8)
            c.drawString(self.LE, 24, lien_he[:70])


def _draw_cover(canv: rl_canvas.Canvas, doc) -> None:
    """Bìa: dải màu đậm, tiêu đề lớn, gạch cam có chấm — theo mẫu."""
    meta: ReportMeta = doc.meta
    canv.saveState()

    # Logo đặt trên nền trắng phía trên dải màu, như vị trí logo ở mẫu tham chiếu.
    logo = meta.logo()
    if logo:
        size = 58
        canv.drawImage(str(logo), _MARGIN, _PAGE_H - 96, width=size, height=size,
                       mask="auto", preserveAspectRatio=True)
        if meta.company:
            canv.setFillColor(colors.HexColor(BRAND))
            canv.setFont(FONT_B, 13)
            canv.drawString(_MARGIN + size + 14, _PAGE_H - 66, meta.company)

    band_top, band_h = _PAGE_H - 120, 300
    canv.setFillColor(colors.HexColor(BRAND))
    canv.rect(0, band_top - band_h, _PAGE_W, band_h, stroke=0, fill=1)

    # Nhãn nhỏ trên dải màu
    canv.setFillColor(colors.HexColor(ON_BRAND))
    canv.setFont(FONT_B, 9)
    canv.drawString(_MARGIN, band_top - 42, "BÁO CÁO PHÁP LÝ CHUYÊN ĐỀ THEO NGÀNH")

    canv.setFillColor(colors.white)
    canv.setFont(FONT_B, 30)
    industry = meta.industry.upper()
    if len(industry) > 26:
        head, _, tail = industry.rpartition(" & ")
        lines = [head + " &", tail] if head else [industry[:26], industry[26:]]
    else:
        lines = [industry]
    y = band_top - 110
    for ln in lines[:2]:
        canv.drawString(_MARGIN, y, ln)
        y -= 36

    # Khối tiêu đề dưới dải màu
    canv.setFillColor(colors.HexColor(DARK_GREEN))
    canv.setFont(FONT_B, 22)
    canv.drawString(_MARGIN, band_top - band_h - 70, "Cập nhật khung pháp lý")
    canv.drawString(_MARGIN, band_top - band_h - 98, "và nghĩa vụ tuân thủ")

    # Gạch cam có chấm — chi tiết nhận diện của mẫu
    ry = band_top - band_h - 88
    canv.setFillColor(colors.HexColor(ORANGE))
    canv.circle(_MARGIN + 320, ry, 4.5, stroke=0, fill=1)
    canv.setStrokeColor(colors.HexColor(ORANGE))
    canv.setLineWidth(2)
    canv.line(_MARGIN + 326, ry, _PAGE_W - _MARGIN, ry)

    canv.setFillColor(colors.HexColor(INK_SOFT))
    canv.setFont(FONT, 11)
    canv.drawString(_MARGIN, band_top - band_h - 130, meta.period)
    canv.drawString(_MARGIN, band_top - band_h - 148,
                    f"Dữ liệu chốt đến ngày {meta.cutoff}")
    if meta.scope:
        canv.setFont(FONT, 9)
        canv.drawString(_MARGIN, band_top - band_h - 172, meta.scope[:105])

    if meta.contact:
        canv.setFont(FONT, 8.5)
        canv.setFillColor(colors.HexColor(INK_SOFT))
        canv.drawString(_MARGIN, 54, meta.contact[:110])

    canv.restoreState()


# ── Markdown → flowables ─────────────────────────────────────────────────────
def _inline(text: str) -> str:
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", text)
    return text


def _figure_block(fig: Figure, st: dict) -> KeepTogether:
    img = Image(io.BytesIO(fig.png))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = _CONTENT_W
    img.drawHeight = _CONTENT_W * ratio
    return KeepTogether([
        Spacer(1, 10),
        Paragraph(f"BIỂU ĐỒ {fig.number}:", st["fig_num"]),
        Paragraph(_inline(fig.title), st["fig_title"]),
        img,
        Paragraph(fig.source, st["source"]),
        Spacer(1, 12),
    ])


def _callout(title: str, paragraphs: list[str], st: dict) -> KeepTogether:
    """Hộp nhận định: ô xanh + thanh cam + thân nền kem."""
    header = Table(
        [[Paragraph("", st["callout_h"]), Paragraph(_inline(title), st["callout_h"])]],
        colWidths=[26, _CONTENT_W - 26], rowHeights=[20],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(DARK_GREEN)),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(ORANGE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (1, 0), (1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    body = Table(
        [[[Paragraph(_inline(p), st["callout"]) for p in paragraphs]]],
        colWidths=[_CONTENT_W],
    )
    body.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(CREAM)),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return KeepTogether([Spacer(1, 10), header, body, Spacer(1, 12)])


def _table(rows: list[list[str]], st: dict) -> Table:
    header, *body = rows
    ncol = len(header)
    data = [[Paragraph(_inline(c), st["cell_h"]) for c in header]]
    for r in body:
        r = (r + [""] * ncol)[:ncol]
        data.append([Paragraph(_inline(c), st["cell"]) for c in r])
    widths = [_CONTENT_W / ncol] * ncol
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(DARK_GREEN)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F7F5")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(RULE)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _strip_own_cover(md: str) -> str:
    """Bỏ khối tiêu đề mà LLM tự sinh ở đầu báo cáo.

    Trang bìa đã hiển thị tên ngành, kỳ báo cáo và mốc chốt dữ liệu; giữ lại
    khối đó trong thân bài là lặp và đẩy nội dung thật xuống dưới.
    """
    lines = md.splitlines()
    start = 0
    for idx, line in enumerate(lines[:12]):
        s = line.strip().lstrip("#* ").upper()
        if s.startswith("TÓM TẮT") or "TÓM TẮT ĐIỀU HÀNH" in s:
            start = idx
            break
        if s.startswith("---") and idx > 0:
            start = idx + 1
    return "\n".join(lines[start:]).lstrip("-\n ")


def _parse(md: str, meta: ReportMeta, st: dict) -> list:
    story: list = []
    figures = list(meta.figures)
    pending_table: list[list[str]] = []
    quote_buf: list[str] = []
    disclaimer_buf: list[str] = []
    in_disclaimer = False
    figures_placed = False

    def flush_table():
        nonlocal pending_table
        if len(pending_table) >= 2:
            story.append(Spacer(1, 4))
            story.append(_table(pending_table, st))
            story.append(Spacer(1, 10))
        pending_table = []

    # Cụm cho biết khối trích dẫn thực chất là lời miễn trách nhiệm, không phải
    # nhận định chuyên môn — gắn sai nhãn trên tài liệu gửi khách là sai bản chất.
    DAU_HIEU_MIEN_TRACH = (
        "miễn trách", "chỉ mang tính chất tham khảo", "không thay thế",
        "không phải là ý kiến tư vấn",
    )

    def flush_quote():
        nonlocal quote_buf
        if quote_buf:
            joined = " ".join(quote_buf).lower()
            tieu_de = ("TUYÊN BỐ MIỄN TRÁCH NHIỆM"
                       if any(d in joined for d in DAU_HIEU_MIEN_TRACH)
                       else "NHẬN ĐỊNH")
            story.append(_callout(tieu_de, quote_buf, st))
            quote_buf = []

    def flush_disclaimer():
        """Miễn trách nhiệm vào hộp kem — vừa nổi bật, vừa không rơi bơ vơ một trang."""
        nonlocal disclaimer_buf, in_disclaimer
        if disclaimer_buf:
            story.append(_callout("TUYÊN BỐ MIỄN TRÁCH NHIỆM", disclaimer_buf, st))
            disclaimer_buf = []
        in_disclaimer = False

    for raw in md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                continue
            pending_table.append(cells)
            continue
        flush_table()

        if stripped.startswith(">"):
            quote_buf.append(stripped.lstrip("> ").strip())
            continue
        flush_quote()

        if not stripped or set(stripped) <= {"-", "*", "_"} and len(stripped) >= 3:
            continue

        # Mục miễn trách nhiệm có thể là tiêu đề (#### …) hoặc mục đánh số
        # (2. **Tuyên bố miễn trách nhiệm:**) tuỳ cách LLM viết — bắt cả hai.
        if not in_disclaimer and "miễn trách nhiệm" in stripped.lower():
            flush_disclaimer()
            in_disclaimer = True
            continue

        if stripped.startswith("#"):
            flush_disclaimer()
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped.lstrip("# ").strip()
            key = "h1" if level <= 2 else ("h2" if level == 3 else "h3")
            # Biểu đồ đặt trọn ở cuối phần tóm tắt, ngay TRƯỚC chương đầu tiên.
            # Chèn sau một tiêu đề phụ bất kỳ sẽ tách tiêu đề khỏi bảng của nó.
            if (not figures_placed and figures
                    and re.match(r"^(CHƯƠNG|PHẦN)\b", text.strip(), re.I)):
                for fig in figures:
                    story.append(_figure_block(fig, st))
                figures_placed = True
            story.append(Paragraph(_inline(text), st[key]))
            continue

        if in_disclaimer:
            disclaimer_buf.append(re.sub(r"^(\d+\.|[-*•])\s+", "", stripped))
            continue

        if re.match(r"^[-*•]\s+", stripped):
            story.append(Paragraph("•  " + _inline(re.sub(r"^[-*•]\s+", "", stripped)),
                                   st["bullet"]))
            continue
        if re.match(r"^\d+\.\s+", stripped):
            story.append(Paragraph(_inline(stripped), st["bullet"]))
            continue

        story.append(Paragraph(_inline(stripped), st["body"]))

    flush_table()
    flush_quote()
    flush_disclaimer()
    if not figures_placed:
        for fig in figures:
            story.append(_figure_block(fig, st))
    return story


def build_report_pdf(md_text: str, out_path: Path, meta: ReportMeta) -> Path:
    """Dựng PDF hoàn chỉnh: bìa + nội dung + biểu đồ."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Đăng ký font ở đây, không ở cấp module: máy thiếu font thì lỗi phải nổ ra
    # đúng lúc dựng PDF, chứ không làm chết cả việc import module.
    _register_fonts()
    st = _styles()

    doc = BaseDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=64, bottomMargin=54,
        title=f"Báo cáo pháp lý ngành {meta.industry}",
        author=meta.company or "Báo cáo pháp lý",
    )
    doc.meta = meta

    cover_frame = Frame(0, 0, _PAGE_W, _PAGE_H, id="cover",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    body_frame = Frame(_MARGIN, 54, _CONTENT_W, _PAGE_H - 64 - 54, id="body",
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=_draw_cover),
        PageTemplate(id="body", frames=[body_frame]),
    ])

    # NextPageTemplate là bắt buộc: thiếu nó thì hàm vẽ bìa chạy trên MỌI trang
    # và dải màu đè lên toàn bộ nội dung.
    story: list = [NextPageTemplate("body"), PageBreak()]
    story += _parse(_strip_own_cover(md_text), meta, st)

    # Thư ngỏ hợp tác đóng lại báo cáo. Là Flowable nên nó tự xuống trang mới
    # khi trang cuối không đủ chỗ, thay vì đè lên chữ.
    if (meta.partner_pitch or "").strip():
        story.append(Spacer(1, 22))
        story.append(KhoiThuNgo(meta, _CONTENT_W))

    doc.build(story, canvasmaker=lambda *a, **k: _Canvas(*a, meta=meta, **k))
    return out_path
