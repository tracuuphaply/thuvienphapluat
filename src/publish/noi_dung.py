"""Ruột văn bản và biểu mẫu, cắt thành mảnh HTML để trang trợ lý tải khi cần.

VÌ SAO LÀ FILE RỜI, KHÔNG NHÉT VÀO du-lieu.json. Bộ dữ liệu trợ lý tải ĐỦ MỘT
LẦN lúc mở trang — 1,9 MB cho 4.201 văn bản và 653 biểu mẫu. Ruột thì lớn hơn
hẳn: riêng 653 thân biểu mẫu đã là 8,4 triệu ký tự. Nhét vào đó là bắt mọi người
tải toàn bộ kho chữ chỉ để xem danh sách, trong khi một phiên tra cứu thường chỉ
mở vài tài liệu. Mỗi tài liệu một file, tải đúng cái được mở.

VÌ SAO DỰNG SẴN RA HTML, KHÔNG GỬI MARKDOWN. Trang trợ lý là một file tĩnh không
có bước build; gửi Markdown sang là phải mang theo một bộ đọc Markdown trong
trình duyệt, tức là dựng lại md_toi_gian bằng JavaScript và có hai bộ đọc phải
khớp nhau. Dựng sẵn thì bộ đọc chỉ có một, nằm ở Python, và đã có test.

NGUỒN NÀO ĐƯỢC ĐỌC, và đây là ràng buộc chứ không phải lựa chọn:
  · biểu mẫu → `body_md_path`  — Markdown do src/forms/renderer.py dựng lại.
  · văn bản  → `clean_text_path` — Markdown làm sạch từ HTML Bộ Tư pháp.
TUYỆT ĐỐI KHÔNG đọc `body_html_path` (HTML gốc Thư viện Pháp luật, nguyên liệu
nội bộ) và cũng không đọc `fulltext_path` (HTML thô chưa làm sạch). Hai đường đó
mang theo thẻ, kiểu dáng và dấu vết của trang nguồn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from src.publish.md_toi_gian import sang_html

logger = logging.getLogger(__name__)

THU_MUC = "noi-dung"


@dataclass
class ThongKeNoiDung:
    van_ban: int = 0
    bieu_mau: int = 0
    kich_thuoc_kb: int = 0
    thieu_van_ban: int = 0
    thieu_bieu_mau: int = 0


def _doc(duong: str | None) -> str:
    """Đọc file Markdown nếu có. Trả chuỗi rỗng cho mọi ca không đọc được.

    Đường dẫn trong kho là đường dẫn TUYỆT ĐỐI trên máy đã chạy pipeline. Dựng
    trang ở máy khác thì file không có ở đó — đó là chuyện bình thường, không
    phải lỗi, nên không ném ngoại lệ mà đếm vào `thieu_*` để bản dựng nói ra.
    """
    if not duong:
        return ""
    try:
        p = Path(duong)
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    except OSError as e:
        logger.warning("Không đọc được ruột %s: %s", duong, e)
        return ""


def _bo_dau_trang_bieu_mau(md: str) -> str:
    """Cắt phần đầu trang mà src/forms/renderer.py chèn, giữ lại đúng RUỘT mẫu.

    File `body_md_path` mở đầu bằng một khối gồm `# tiêu đề`, `**Căn cứ:**`,
    `**Cập nhật:**`, `**Nguồn:** <URL Thư viện Pháp luật>` rồi tới trích dẫn
    "> Bản dựng lại…". Cả khối ấy phải đi, vì ba lý do:
      · popup đã có tiêu đề, căn cứ và khối cảnh báo "Bản dựng lại" của riêng
        nó — để nguyên là nói cùng một câu hai lần, cách nhau ba dòng;
      · `md_toi_gian` KHÔNG dựng tiêu đề `#`, nên dòng đó hiện ra nguyên xi
        thành chữ "# Tên biểu mẫu";
      · dòng `**Nguồn:**` mang URL Thư viện Pháp luật vào giữa thân mẫu.

    Mốc cắt là chính dòng trích dẫn, y như html_site và form_exporter làm. Nhận
    cả khi nó đứng ngay ĐẦU file: `find("\\n> Bản dựng lại")` đòi một dòng xuống
    ở trước, nên một file không có phần đầu trang sẽ lọt nguyên khối qua đây.
    """
    moc = "> Bản dựng lại"
    dau = 0 if md.startswith(moc) else md.find("\n" + moc)
    if dau < 0:
        return md.strip()
    cuoi = md.find("\n\n", dau + 1)
    return (md[cuoi:] if cuoi > 0 else "").strip()


def xuat_noi_dung(session, out_dir: Path) -> tuple[ThongKeNoiDung, set[str], set[str]]:
    """Ghi mảnh ruột cho mọi tài liệu ĐÃ ĐĂNG có sẵn nguồn.

    Trả về (thống kê, slug văn bản có ruột, slug biểu mẫu có ruột). Hai tập slug
    đi thẳng vào bộ dữ liệu trợ lý: trang phải biết TRƯỚC tài liệu nào có ruột,
    không thì mỗi lần mở một tài liệu không có ruột là một lượt tải hỏng 404 và
    một dòng đỏ trong bảng điều khiển.
    """
    out_dir = Path(out_dir)
    tk = ThongKeNoiDung()
    co_vb: set[str] = set()
    co_bm: set[str] = set()
    tong = 0

    d_vb = out_dir / THU_MUC / "van-ban"
    d_bm = out_dir / THU_MUC / "bieu-mau"
    d_vb.mkdir(parents=True, exist_ok=True)
    d_bm.mkdir(parents=True, exist_ok=True)

    for slug, duong in session.execute(text(
        # `is_vbqppl` PHẢI có, cho khớp hai bộ xuất kia: `assistant_export._van_ban()`
        # lọc `is_vbqppl = 1`, `html_site.xuat_van_ban()` cũng vậy. Thiếu nó ở đây
        # thì ruột của văn bản KHÔNG phải quy phạm vẫn được ghi ra site — thành
        # file mồ côi: không trang nào trỏ tới, không mục nào trong bộ dữ liệu trợ
        # lý mang cờ `r`, mà nội dung thì vẫn nằm công khai trên máy chủ.
        "SELECT public_slug, clean_text_path FROM documents "
        "WHERE public_slug IS NOT NULL AND is_vbqppl = 1"
    )).fetchall():
        md = _doc(duong)
        if not md.strip():
            tk.thieu_van_ban += 1
            continue
        html = sang_html(md.strip(), kieu="van_ban")
        if not html:
            tk.thieu_van_ban += 1
            continue
        (d_vb / f"{slug}.html").write_text(html, encoding="utf-8")
        co_vb.add(slug)
        tk.van_ban += 1
        tong += len(html.encode())

    for slug, duong in session.execute(text(
        "SELECT public_slug, body_md_path FROM legal_forms "
        "WHERE public_slug IS NOT NULL"
    )).fetchall():
        md = _bo_dau_trang_bieu_mau(_doc(duong))
        if not md:
            tk.thieu_bieu_mau += 1
            continue
        html = sang_html(md, kieu="bieu_mau")
        if not html:
            tk.thieu_bieu_mau += 1
            continue
        (d_bm / f"{slug}.html").write_text(html, encoding="utf-8")
        co_bm.add(slug)
        tk.bieu_mau += 1
        tong += len(html.encode())

    tk.kich_thuoc_kb = tong // 1024
    logger.info("Xuất ruột: %d văn bản, %d biểu mẫu, %d KB (thiếu nguồn: %d VB, %d BM)",
                tk.van_ban, tk.bieu_mau, tk.kich_thuoc_kb,
                tk.thieu_van_ban, tk.thieu_bieu_mau)
    return tk, co_vb, co_bm
