"""
PDF Exporter Utility for Legal Reports.
Converts Markdown legal compliance reports into beautifully styled PDF documents
with full Vietnamese Unicode support using ReportLab.
"""
import os
import re
import datetime
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional


from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.units import inch, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from src.config import DATA_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

# Register Vietnamese TrueType Fonts
FONT_NAME = "VietnameseArial"
FONT_BOLD_NAME = "VietnameseArialBold"
FONT_ITALIC_NAME = "VietnameseArialItalic"

def _register_fonts():
    """Register macOS system Arial fonts for Vietnamese rendering."""
    try:
        font_dir = "/System/Library/Fonts/Supplemental"
        arial_regular = os.path.join(font_dir, "Arial.ttf")
        arial_bold = os.path.join(font_dir, "Arial Bold.ttf")
        arial_italic = os.path.join(font_dir, "Arial Italic.ttf")

        if os.path.exists(arial_regular):
            pdfmetrics.registerFont(TTFont(FONT_NAME, arial_regular))
        if os.path.exists(arial_bold):
            pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, arial_bold))
        else:
            pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, arial_regular))
            
        if os.path.exists(arial_italic):
            pdfmetrics.registerFont(TTFont(FONT_ITALIC_NAME, arial_italic))
        else:
            pdfmetrics.registerFont(TTFont(FONT_ITALIC_NAME, arial_regular))

        # Register family mapping
        pdfmetrics.registerFontFamily(
            FONT_NAME,
            normal=FONT_NAME,
            bold=FONT_BOLD_NAME,
            italic=FONT_ITALIC_NAME
        )
    except Exception as e:
        logger.warning(f"Failed to register system TTF fonts: {e}")

_register_fonts()


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and draw page numbers 'Trang X / Y'."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont(FONT_NAME, 8)
        self.setFillColor(colors.HexColor("#6B7280"))
        
        # Header (on pages after cover page)
        if self._pageNumber > 1:
            self.drawString(54, 800, "BÁO CÁO PHÁP LÝ CHUYÊN ĐỀ DÀNH CHO DOANH NGHIỆP")
            self.setStrokeColor(colors.HexColor("#E5E7EB"))
            self.setLineWidth(0.5)
            self.line(54, 792, 541, 792)

        # Footer (all pages)
        page_text = f"Trang {self._pageNumber} / {page_count}"
        self.drawRightString(541, 36, page_text)
        self.drawString(54, 36, "🔒 Dữ liệu trích xuất từ Hệ thống Quản trị Pháp lý Doanh nghiệp")
        self.setStrokeColor(colors.HexColor("#E5E7EB"))
        self.setLineWidth(0.5)
        self.line(54, 48, 541, 48)
        
        self.restoreState()


def convert_md_to_pdf(md_text: str, output_path: Optional[Path] = None, report_title: str = "BÁO CÁO PHÁP LÝ CHUYÊN ĐỀ") -> Path:
    """
    Convert Markdown report string into a professionally styled PDF file.
    """
    if output_path is None:
        output_dir = DATA_DIR / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"Bao_Cao_Phap_Ly_{datetime.date.today().strftime('%Y%m%d')}_{os.urandom(2).hex()}.pdf"
        output_path = output_dir / filename

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Custom Color Palette
    PRIMARY_COLOR = colors.HexColor("#1E3A8A")     # Navy Blue
    SECONDARY_COLOR = colors.HexColor("#2563EB")   # Blue Accent
    TEXT_COLOR = colors.HexColor("#1F2937")        # Dark Slate
    BG_LIGHT = colors.HexColor("#F8FAFC")          # Light Soft Blue/Grey
    BORDER_COLOR = colors.HexColor("#CBD5E1")      # Border Grey

    # Custom Typography Styles
    title_style = ParagraphStyle(
        'DocTitle',
        fontName=FONT_BOLD_NAME,
        fontSize=20,
        leading=24,
        textColor=colors.white,
        alignment=1, # Center
        spaceAfter=10
    )

    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        fontName=FONT_NAME,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#DBEAFE"),
        alignment=1,
        spaceAfter=5
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        fontName=FONT_BOLD_NAME,
        fontSize=14,
        leading=18,
        textColor=PRIMARY_COLOR,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        fontName=FONT_BOLD_NAME,
        fontSize=12,
        leading=16,
        textColor=SECONDARY_COLOR,
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True
    )

    h3_style = ParagraphStyle(
        'Heading3_Custom',
        fontName=FONT_BOLD_NAME,
        fontSize=10,
        leading=14,
        textColor=TEXT_COLOR,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        fontName=FONT_NAME,
        fontSize=9.5,
        leading=13.5,
        textColor=TEXT_COLOR,
        spaceAfter=6
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        fontName=FONT_NAME,
        fontSize=9.5,
        leading=13.5,
        textColor=TEXT_COLOR,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=4
    )

    table_cell_style = ParagraphStyle(
        'TableCell',
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=11.5,
        textColor=TEXT_COLOR
    )

    table_header_style = ParagraphStyle(
        'TableHeader',
        fontName=FONT_BOLD_NAME,
        fontSize=8.5,
        leading=11.5,
        textColor=colors.white
    )

    blockquote_style = ParagraphStyle(
        'Blockquote',
        fontName=FONT_ITALIC_NAME,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#334155"),
        leftIndent=15,
        rightIndent=15,
        spaceBefore=6,
        spaceAfter=6
    )

    story = []

    # Parse Markdown lines into ReportLab Flowables
    lines = md_text.splitlines()
    in_table = False
    table_rows = []
    
    for line in lines:
        stripped = line.strip()

        # Handle Markdown Tables
        if stripped.startswith("|") and stripped.endswith("|"):
            # Check if separator line
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                continue
            
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            table_rows.append(cells)
            in_table = True
            continue
        elif in_table:
            # End of table block -> render table
            if table_rows:
                _add_table_to_story(story, table_rows, table_header_style, table_cell_style, BORDER_COLOR, PRIMARY_COLOR)
            table_rows = []
            in_table = False

        if not stripped:
            story.append(Spacer(1, 4))
            continue

        # Handle H1 Title (# Title)
        if stripped.startswith("# "):
            title_text = _clean_md_formatting(stripped[2:])
            # Draw Header Banner
            banner_data = [[
                Paragraph(f"<b>{title_text.upper()}</b>", title_style)
            ]]
            banner_table = Table(banner_data, colWidths=[487])
            banner_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), PRIMARY_COLOR),
                ('TOPPADDING', (0, 0), (-1, -1), 16),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 16),
                ('LEFTPADDING', (0, 0), (-1, -1), 16),
                ('RIGHTPADDING', (0, 0), (-1, -1), 16),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(banner_table)
            story.append(Spacer(1, 14))

        # Handle H2 (## Chapter)
        elif stripped.startswith("## "):
            h2_text = _clean_md_formatting(stripped[3:])
            story.append(HRFlowable(width="100%", thickness=1, color=SECONDARY_COLOR, spaceBefore=10, spaceAfter=4))
            story.append(Paragraph(h2_text, h1_style))

        # Handle H3 (### Section)
        elif stripped.startswith("### "):
            h3_text = _clean_md_formatting(stripped[4:])
            story.append(Paragraph(h3_text, h2_style))

        # Handle H4 (#### Subsection)
        elif stripped.startswith("#### "):
            h4_text = _clean_md_formatting(stripped[5:])
            story.append(Paragraph(h4_text, h3_style))

        # Handle Blockquotes (> Excerpt)
        elif stripped.startswith("> "):
            bq_text = _clean_md_formatting(stripped[2:])
            bq_table = Table([[Paragraph(bq_text, blockquote_style)]], colWidths=[487])
            bq_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), BG_LIGHT),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('LINELEFT', (0, 0), (-1, -1), 3, SECONDARY_COLOR),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(bq_table)
            story.append(Spacer(1, 4))

        # Handle Bullet items (- item or * item)
        elif stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped):
            item_text = _clean_md_formatting(re.sub(r"^([\-\*]|\d+\.)\s+", "", stripped))
            formatted = _convert_inline_md(item_text)
            story.append(Paragraph(f"• {formatted}", bullet_style))

        # Regular Paragraph
        else:
            formatted = _convert_inline_md(stripped)
            story.append(Paragraph(formatted, body_style))

    # Flush remaining table if at end of file
    if in_table and table_rows:
        _add_table_to_story(story, table_rows, table_header_style, table_cell_style, BORDER_COLOR, PRIMARY_COLOR)

    # Build PDF
    doc.build(story, canvasmaker=NumberedCanvas)
    logger.info(f"Generated PDF report at: {output_path}")
    return output_path


def _clean_md_formatting(text: str) -> str:
    """Remove raw markdown headers/tags for clean title text."""
    text = re.sub(r"[\*\_\`]", "", text)
    return text.strip()


def _convert_inline_md(text: str) -> str:
    """Convert Markdown inline formatting (**bold**, *italic*, `code`) into ReportLab XML tags."""
    # Bold **text** -> <b>text</b>
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    # Italic *text* -> <i>text</i>
    text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
    # Code `text` -> <font name="Courier">\1</font>
    text = re.sub(r"`(.*?)`", r"<b><font color='#1E3A8A'>\1</font></b>", text)
    return text


def _add_table_to_story(story: list, table_rows: list, header_style: ParagraphStyle, cell_style: ParagraphStyle, border_color, header_bg):
    """Convert raw Markdown table rows into a styled ReportLab Table Flowable."""
    if not table_rows:
        return

    formatted_rows = []
    # Header row
    header_cells = [Paragraph(cell, header_style) for cell in table_rows[0]]
    formatted_rows.append(header_cells)

    # Body rows
    for row in table_rows[1:]:
        body_cells = [Paragraph(_convert_inline_md(cell), cell_style) for cell in row]
        formatted_rows.append(body_cells)

    # Calculate column widths dynamically to fit page width (487pt)
    num_cols = len(table_rows[0])
    col_width = 487 / max(num_cols, 1)
    col_widths = [col_width] * num_cols

    t = Table(formatted_rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))

    story.append(Spacer(1, 4))
    story.append(t)
    story.append(Spacer(1, 8))
