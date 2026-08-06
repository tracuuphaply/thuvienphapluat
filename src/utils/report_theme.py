"""
Ngôn ngữ thiết kế cho báo cáo pháp lý gửi doanh nghiệp.

Bảng màu và bố cục phỏng theo mẫu báo cáo nghiên cứu của Thomson Reuters
Institute: bìa có dải màu, tiêu đề chương màu cam lớn, khối FIGURE có chú thích
nguồn, hộp nhận định nền kem.

Màu chuỗi dữ liệu KHÔNG lấy nguyên bản màu thương hiệu: xanh rêu #122F20 của
mẫu quá tối và bạc màu để làm màu cột (validator báo FAIL cả dải sáng lẫn ngưỡng
chroma). Nó được giữ cho chữ và nền, còn dữ liệu dùng bộ màu đã kiểm chứng.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

# ── Bảng màu ─────────────────────────────────────────────────────────────────
# Tone thương hiệu thongtincty, đọc trực tiếp từ file logo:
#   nền chính #003CA7 · hoạ tiết #3363B8 · chữ trắng
# Bố cục kế thừa mẫu Thomson Reuters, nhưng màu thì thay hẳn sang hệ xanh.
BRAND = "#003CA7"        # xanh hoàng gia — dải bìa, đầu bảng, tiêu đề chương
BRAND_DEEP = "#00276E"   # xanh đậm hơn — ô vuông hộp nhận định
BRAND_SOFT = "#3363B8"   # xanh nhạt — hoạ tiết
ON_BRAND = "#A8C3F0"     # chữ phụ ĐẶT TRÊN nền xanh đậm; #3363B8 quá chìm
TINT = "#EAF0FB"         # nền hộp nhận định (thay nền kem của mẫu gốc)

INK = "#212223"          # chữ thân bài
INK_SOFT = "#4E4E4F"     # chữ phụ
RULE = "#DEDEDE"         # đường kẻ mảnh
SURFACE = "#FCFCFB"

# Màu cột dữ liệu KHÔNG dùng thẳng #003CA7: validator báo nằm ngoài dải sáng
# (L 0.402 so với dải 0.43–0.77), cột sẽ nặng và bí. #1A56C4 cùng họ xanh nhưng
# đạt chuẩn.
DATA_BLUE = "#1A56C4"

# Giữ tên cũ để phần còn lại của mã không phải sửa đồng loạt.
ORANGE = BRAND
DARK_GREEN = BRAND_DEEP
CREAM = TINT

# Bộ màu TRẠNG THÁI HIỆU LỰC — đã qua scripts/validate_palette.js, PASS cả 5 mục:
# dải sáng, ngưỡng chroma, phân tách mù màu (ΔE 8.2 deutan), ngưỡng thị lực
# thường (ΔE 18.8) và tương phản nền (≥3:1).
STATUS_COLORS = {
    "Còn hiệu lực": "#1F7A52",
    "Hết hiệu lực một phần": "#B08415",
    "Hết hiệu lực toàn bộ": "#C0281A",
    "Chưa có hiệu lực": "#5B8DEF",
}
STATUS_FALLBACK = "#6B7280"

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

_font = fm.FontProperties(fname=FONT_PATH)
_font_bold = fm.FontProperties(fname=FONT_BOLD_PATH)


@dataclass
class Figure:
    """Một khối FIGURE trong báo cáo."""
    number: int
    title: str
    png: bytes
    source: str = "Nguồn: Cơ sở dữ liệu văn bản quy phạm pháp luật"
    height_cm: float = 6.0


def _finish(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight",
                facecolor=SURFACE, edgecolor="none")
    plt.close(fig)
    return buf.getvalue()


def _style_axes(ax) -> None:
    """Trục và lưới lùi về sau, để dữ liệu nổi lên."""
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(RULE)
    ax.tick_params(axis="both", length=0, labelsize=8, colors=INK_SOFT)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontproperties(_font)
    ax.set_facecolor(SURFACE)


def bar_counts(labels: list[str], values: list[int], *, color: str = DATA_BLUE,
               width_in: float = 6.4, unit: str = "văn bản") -> bytes:
    """Thanh ngang một chuỗi — so sánh độ lớn giữa các hạng mục.

    Một chuỗi thì không cần chú giải: nhãn hạng mục nằm ngay cạnh thanh, và giá
    trị được ghi thẳng ở đầu thanh nên không ai phải dò theo trục.
    """
    n = len(labels)
    fig, ax = plt.subplots(figsize=(width_in, max(1.4, 0.42 * n + 0.5)))
    y = range(n)
    ax.barh(list(y), values, height=0.62, color=color, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xticks([])
    _style_axes(ax)
    ax.spines["bottom"].set_visible(False)

    span = max(values) if values else 1
    for i, v in enumerate(values):
        ax.text(v + span * 0.015, i, f"{v:,}".replace(",", "."), va="center",
                ha="left", fontproperties=_font_bold, fontsize=9, color=INK)
    ax.set_xlim(0, span * 1.14)
    return _finish(fig)


def bar_status(counts: dict[str, int], *, width_in: float = 6.4) -> bytes:
    """Thanh ngang theo trạng thái hiệu lực — dùng bộ màu trạng thái đã kiểm chứng.

    Màu không bao giờ là tín hiệu duy nhất: mỗi thanh đều có nhãn chữ bên trái và
    con số bên phải, đúng yêu cầu khi dùng màu trạng thái.
    """
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    colors = [STATUS_COLORS.get(k, STATUS_FALLBACK) for k in labels]

    fig, ax = plt.subplots(figsize=(width_in, max(1.4, 0.46 * len(items) + 0.4)))
    y = range(len(items))
    ax.barh(list(y), values, height=0.6, color=colors, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xticks([])
    _style_axes(ax)
    ax.spines["bottom"].set_visible(False)

    span = max(values) if values else 1
    total = sum(values) or 1
    for i, v in enumerate(values):
        ax.text(v + span * 0.015, i, f"{v}  ({100*v//total}%)", va="center",
                ha="left", fontproperties=_font_bold, fontsize=9, color=INK)
    ax.set_xlim(0, span * 1.26)
    return _finish(fig)


def timeline_effective_dates(months: list[str], counts: list[int], *,
                             width_in: float = 6.4) -> bytes:
    """Cột theo tháng — mốc hiệu lực sắp tới.

    Đây là biểu đồ có giá trị nhất với chủ doanh nghiệp: nó trả lời "tháng nào
    tôi phải chuẩn bị gì", chứ không chỉ mô tả kho văn bản.
    """
    fig, ax = plt.subplots(figsize=(width_in, 2.3))
    x = range(len(months))
    ax.bar(list(x), counts, width=0.6, color=DATA_BLUE, zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(months, rotation=0)
    ax.set_yticks([])
    _style_axes(ax)

    for i, v in enumerate(counts):
        if v:
            ax.text(i, v + max(counts) * 0.04, str(v), ha="center",
                    fontproperties=_font_bold, fontsize=9, color=INK)
    ax.set_ylim(0, max(counts) * 1.22 if counts and max(counts) else 1)
    return _finish(fig)
