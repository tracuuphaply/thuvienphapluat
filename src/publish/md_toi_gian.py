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

HAI CHẾ ĐỘ, vì hai nguồn phát ra hai thứ khác nhau.
    · `kieu="bieu_mau"` (mặc định) — nguồn là src/forms/renderer.py.
    · `kieu="van_ban"`             — nguồn là pipeline.text_processor.html_to_clean_text,
      tức HTML Bộ Tư pháp đã làm sạch. Cùng tập cú pháp, nhưng ba chỗ phải xử lý
      khác đi; xem `sang_html`.

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
# Đậm/nghiêng của VĂN BẢN nới hơn: cho phép khoảng trắng sát bên trong cặp dấu.
# HTML Bộ Tư pháp có `<b>Quy định… </b>` với dấu cách trước thẻ đóng, ra thành
# `**Quy định… **`, và mẫu chặt `(?<=\S)\*\*` không khớp — dấu sao hiện nguyên
# ra màn hình. Đo trên 004/2025/TT-BNV: ba dòng tiêu đề đều dính.
_DAM_NOI = re.compile(r"\*\*\s*(\S.*?\S|\S)\s*\*\*", re.S)
_NGHIENG_NOI = re.compile(r"(?<!\*)\*\s*(\S[^*\n]*?\S|\S)\s*\*(?!\*)")
# Dấu sao CÒN SÓT sau khi ghép cặp. Không phải rác vô cớ: <b> của nguồn bao qua
# NHIỀU thẻ khối, mà mỗi thẻ khối thành một đoạn riêng — dấu mở nằm ở đoạn này,
# dấu đóng ở đoạn cách đó bảy đoạn. Markdown không có cặp nào bắc qua đoạn được,
# nên chúng KHÔNG BAO GIỜ ghép được và chỉ còn cách bỏ đi. Giữ lại là rải `**`
# và `*` khắp mọi văn bản — đúng thứ nhìn thấy trên 004/2025/TT-BNV.
_SAO_SOT = re.compile(r"\*{1,3}")
_PHAN_CACH_BANG = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
# `<hr>` của Bộ Tư pháp ra đúng "---" — không có dấu | nào, khác dòng phân cách bảng.
_KE_NGANG = re.compile(r"^\s*-{3,}\s*$")


def _noi_tuyen(s: str, la_vb: bool = False) -> str:
    """Cú pháp nội tuyến, áp lên chuỗi ĐÃ thoát HTML."""
    s = _MA.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    if la_vb:
        s = _DAM_NOI.sub(lambda m: f"<strong>{m.group(1)}</strong>", s)
        s = _NGHIENG_NOI.sub(lambda m: f"<em>{m.group(1)}</em>", s)
        s = _SAO_SOT.sub("", s)
    else:
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


def _dung_bang(khoi: list[str], la_vb: bool = False) -> str:
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
                  + "".join(f"<th>{_noi_tuyen(o, la_vb)}</th>" for o in _o_bang(dau))
                  + "</tr></thead>")
    ra.append("<tbody>")
    for d in than:
        ra.append("<tr>" + "".join(f"<td>{_noi_tuyen(o, la_vb)}</td>" for o in _o_bang(d))
                  + "</tr>")
    ra.append("</tbody></table></div>")
    return "".join(ra)


def _dung_danh_sach(khoi: list[str]) -> str:
    co_thu_tu = bool(re.match(r"^\s*\d+[.)]\s+", khoi[0]))
    the = "ol" if co_thu_tu else "ul"
    muc = "".join(f"<li>{_noi_tuyen(_MUC_DAU_DONG.sub('', d, count=1))}</li>"
                  for d in khoi)
    return f"<{the}>{muc}</{the}>"


def sang_html(md: str, kieu: str = "bieu_mau") -> str:
    """Chuyển Markdown (tập hẹp ở trên) sang HTML an toàn.

    BA KHÁC BIỆT của `kieu="van_ban"`, mỗi cái vá một lỗi ĐO ĐƯỢC trên đầu ra
    thật của html_to_clean_text, không phải phòng xa:

    1. KHÔNG dựng danh sách. Đây là chỗ nguy hiểm nhất. Dòng "2. Đối tượng áp
       dụng…" là KHOẢN 2 của một điều luật; biến nó thành <ol><li> là giao số
       thứ tự cho trình duyệt đánh lại, và vì mỗi khoản nằm trong một khối riêng
       (html_to_clean_text chèn dòng trống giữa các thẻ khối) nên mọi khoản đều
       thành <ol> mới bắt đầu từ 1 — Khoản 2 hiện ra thành "1.". Với một trang
       tra cứu pháp luật, hiện sai số khoản là nói sai nội dung luật. Giữ nguyên
       dòng chữ thì số nào cũng đúng số ấy.
       Ở biểu mẫu thì ngược lại: danh sách là danh sách thật, và mọi mục nằm
       chung một khối nên đánh số vẫn liền mạch. Nên chế độ cũ giữ nguyên.

    2. GỘP các khối hàng bảng liền nhau. `</tr>` được thay bằng hai dòng xuống,
       nên một bảng 3 hàng ra thành 3 khối cách nhau bởi dòng trống → 3 cái
       <table> một hàng xếp chồng. Bảng phụ lục nào cũng vỡ theo kiểu này.

    3. `---` (từ <hr>) thành đường kẻ ngang, không phải chữ "---". Nó khớp luôn
       cả mẫu dòng phân cách bảng, nên phải xét trước khi vào nhánh bảng.
    """
    if not md:
        return ""
    la_vb = kieu == "van_ban"

    # THOÁT TRƯỚC, phân tích SAU. Đảo thứ tự là mở đường cho thẻ trong nguồn.
    dong = html.escape(md, quote=False).replace("\r\n", "\n").split("\n")

    ra: list[str] = []
    i, n = 0, len(dong)
    while i < n:
        d = dong[i]
        if not d.strip():
            i += 1
            continue

        # ── Đường kẻ ngang (chỉ văn bản; xét TRƯỚC bảng, xem chú thích 3) ──
        if la_vb and _KE_NGANG.match(d):
            ra.append("<hr>")
            i += 1
            continue

        # ── Bảng ──
        if d.lstrip().startswith("|"):
            khoi = []
            while i < n and dong[i].lstrip().startswith("|"):
                khoi.append(dong[i])
                i += 1
            # Gộp qua dòng trống: xem chú thích 2. Chỉ gộp khi dòng có nội dung
            # kế tiếp LẠI là một hàng bảng — hết bảng thì thôi.
            while la_vb:
                j = i
                while j < n and not dong[j].strip():
                    j += 1
                if j >= n or not dong[j].lstrip().startswith("|"):
                    break
                while j < n and dong[j].lstrip().startswith("|"):
                    khoi.append(dong[j])
                    j += 1
                i = j
            ra.append(_dung_bang(khoi, la_vb))
            continue

        # ── Danh sách (KHÔNG áp cho văn bản; xem chú thích 1) ──
        if not la_vb and _MUC_DAU_DONG.match(d):
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
               and not (la_vb and _KE_NGANG.match(dong[i]))
               and not (not la_vb and _MUC_DAU_DONG.match(dong[i]))):
            khoi.append(dong[i].strip())
            i += 1
        # VÒNG LẶP PHẢI LUÔN TIẾN. Nhánh đoạn văn là nhánh cuối, nên nếu điều
        # kiện của nó và điều kiện của một nhánh phía trên lệch nhau — dòng nào
        # đó bị mọi nhánh từ chối — thì `i` đứng yên và hàm quay vô hạn. Đã dựng
        # lại được đúng ca đó bằng cách sửa một dòng ở nhánh đường kẻ ngang: bản
        # dựng treo, không lỗi, không đầu ra. Trong trình duyệt nó là một thẻ
        # đứng máy. Một dòng ở đây đổi hạng lỗi ấy từ TREO thành hiển thị hơi
        # xấu, và đó là đánh đổi đúng.
        if not khoi:
            khoi.append(dong[i].strip())
            i += 1
        # Ngắt dòng trong một đoạn là CÓ NGHĨA ở biểu mẫu: những dòng chấm chấm
        # để điền tay phải giữ đúng vị trí xuống dòng, gộp lại thành một dòng dài
        # là làm hỏng bố cục tờ mẫu.
        # Đoạn CHỈ CÒN dấu sao sau khi dọn thì bỏ hẳn, không để lại <p></p> rỗng:
        # một ô trống cao bằng dòng chữ, rải giữa văn bản, trông như trang lỗi.
        dong_ra = [y for y in (_noi_tuyen(x, la_vb) for x in khoi) if not la_vb or y.strip()]
        if dong_ra:
            ra.append("<p>" + "<br>".join(dong_ra) + "</p>")

    return "\n".join(ra)
