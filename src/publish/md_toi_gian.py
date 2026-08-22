"""Markdown → HTML, đúng tập cú pháp mà biểu mẫu dùng. Không phụ thuộc ngoài.

VÌ SAO KHÔNG DÙNG THƯ VIỆN. Bỏ Quartz là để cắt 91 gói npm; kéo về một thư viện
markdown đầy đủ chỉ để dựng 653 trang biểu mẫu là đi ngược lại. Quan trọng hơn:
thân biểu mẫu do `src/forms/renderer.py` sinh ra, và nó chỉ phát ra HAI cấu trúc —
đoạn văn phẳng và bảng pipe. Một bộ đọc đủ mọi cú pháp CommonMark ở đây là bề mặt
lỗi lớn hơn phần việc thật.

TẬP CÚ PHÁP ĐƯỢC HỖ TRỢ, và chỉ chừng này:
    · đoạn văn        — dòng chữ, ngăn nhau bằng dòng trống
    · bảng pipe       — `| a | b |` kèm dòng phân cách `|---|---|`
    · danh sách       — `- `, `* `, hoặc `1. `
    · đậm / nghiêng   — `**đậm**`, `*nghiêng*`
    · mã              — `` `mã` ``

AN TOÀN LÀ ĐIỀU KIỆN, KHÔNG PHẢI TÍNH NĂNG. Thân biểu mẫu là chữ cào từ Thư viện
Pháp luật — dữ liệu bên ngoài. Nên bước ĐẦU TIÊN là thoát toàn bộ HTML, rồi mới
áp cú pháp lên chuỗi đã thoát. Không có đường nào để thẻ HTML trong nguồn đi
xuyên qua đây, kể cả khi nguồn cố tình chèn.
"""
from __future__ import annotations

import html
import re

__all__ = ["sang_html"]

# Đậm TRƯỚC nghiêng: xử lý ngược lại thì `**x**` bị `*` ăn mất một dấu ở mỗi đầu
# và ra `<em>*x*</em>`. Mã đứng trước cả hai — chữ trong `` ` `` là chữ nguyên văn.
_MA = re.compile(r"`([^`\n]+)`")
_DAM = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_NGHIENG = re.compile(r"(?<!\*)\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\*)")

_MUC_DAU_DONG = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)")
_PHAN_CACH_BANG = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _noi_tuyen(s: str) -> str:
    """Cú pháp nội tuyến, áp lên chuỗi ĐÃ thoát HTML."""
    s = _MA.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    s = _DAM.sub(lambda m: f"<strong>{m.group(1)}</strong>", s)
    s = _NGHIENG.sub(lambda m: f"<em>{m.group(1)}</em>", s)
    return s


def _o_bang(dong: str) -> list[str]:
    """Tách một dòng bảng thành các ô, bỏ dấu | ở hai đầu."""
    d = dong.strip()
    if d.startswith("|"):
        d = d[1:]
    if d.endswith("|"):
        d = d[:-1]
    return [o.strip() for o in d.split("|")]


def _dung_bang(khoi: list[str]) -> str:
    """Bảng pipe → <table>. Dòng đầu là tiêu đề nếu có dòng phân cách theo sau.

    Bảng biểu mẫu thường KHÔNG có hàng tiêu đề thật — `renderer.luoi_bang()` lấy
    hàng đầu của <table> làm tiêu đề vì Markdown bắt buộc phải có. Nên hàng đầu ở
    đây có thể chỉ là một hàng dữ liệu bình thường; vẫn dựng thành <thead> để giữ
    đúng cấu trúc mà bản markdown đã mô tả, không tự ý đoán lại.
    """
    if len(khoi) >= 2 and _PHAN_CACH_BANG.match(khoi[1]):
        dau, than = khoi[0], khoi[2:]
    else:
        dau, than = None, khoi

    ra = ['<div class="cuon"><table>']
    if dau is not None:
        ra.append("<thead><tr>"
                  + "".join(f"<th>{_noi_tuyen(o)}</th>" for o in _o_bang(dau))
                  + "</tr></thead>")
    ra.append("<tbody>")
    for d in than:
        ra.append("<tr>" + "".join(f"<td>{_noi_tuyen(o)}</td>" for o in _o_bang(d))
                  + "</tr>")
    ra.append("</tbody></table></div>")
    return "".join(ra)


def _dung_danh_sach(khoi: list[str]) -> str:
    co_thu_tu = bool(re.match(r"^\s*\d+[.)]\s+", khoi[0]))
    the = "ol" if co_thu_tu else "ul"
    muc = "".join(f"<li>{_noi_tuyen(_MUC_DAU_DONG.sub('', d, count=1))}</li>"
                  for d in khoi)
    return f"<{the}>{muc}</{the}>"


def sang_html(md: str) -> str:
    """Chuyển Markdown (tập hẹp ở trên) sang HTML an toàn."""
    if not md:
        return ""

    # THOÁT TRƯỚC, phân tích SAU. Đảo thứ tự là mở đường cho thẻ trong nguồn.
    dong = html.escape(md, quote=False).replace("\r\n", "\n").split("\n")

    ra: list[str] = []
    i, n = 0, len(dong)
    while i < n:
        d = dong[i]
        if not d.strip():
            i += 1
            continue

        # ── Bảng ──
        if d.lstrip().startswith("|"):
            khoi = []
            while i < n and dong[i].lstrip().startswith("|"):
                khoi.append(dong[i])
                i += 1
            ra.append(_dung_bang(khoi))
            continue

        # ── Danh sách ──
        if _MUC_DAU_DONG.match(d):
            khoi = []
            while i < n and _MUC_DAU_DONG.match(dong[i]):
                khoi.append(dong[i])
                i += 1
            ra.append(_dung_danh_sach(khoi))
            continue

        # ── Đoạn văn: gom các dòng liền nhau ──
        khoi = []
        while (i < n and dong[i].strip()
               and not dong[i].lstrip().startswith("|")
               and not _MUC_DAU_DONG.match(dong[i])):
            khoi.append(dong[i].strip())
            i += 1
        # Ngắt dòng trong một đoạn là CÓ NGHĨA ở biểu mẫu: những dòng chấm chấm
        # để điền tay phải giữ đúng vị trí xuống dòng, gộp lại thành một dòng dài
        # là làm hỏng bố cục tờ mẫu.
        ra.append("<p>" + "<br>".join(_noi_tuyen(x) for x in khoi) + "</p>")

    return "\n".join(ra)
