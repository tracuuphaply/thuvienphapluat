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
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate, PageBreak,
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


def _register_fonts() -> None:
    base = "/System/Library/Fonts/Supplemental"
    for name, file in (
        (FONT, "Arial.ttf"),
        (FONT_B, "Arial Bold.ttf"),
        (FONT_I, "Arial Italic.ttf"),
    ):
        try:
            pdfmetrics.registerFont(TTFont(name, f"{base}/{file}"))
        except Exception:
            pdfmetrics.registerFont(TTFont(name, f"{base}/Arial.ttf"))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_B, italic=FONT_I)


_register_fonts()


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

        foot = self._meta.contact or self._meta.company or ""
        if foot:
            self.drawString(_MARGIN, 30, foot[:110])
        self.restoreState()


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

    doc.build(story, canvasmaker=lambda *a, **k: _Canvas(*a, meta=meta, **k))
    return out_path
