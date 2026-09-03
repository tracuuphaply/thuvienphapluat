"""Sinh trang tra cứu công khai bằng HTML THẲNG, không qua Quartz.

VÌ SAO BỎ QUARTZ. Chuỗi cũ đi vòng: DB → site_exporter → 43 MB markdown →
Quartz (91 gói npm) → HTML. Bước markdown ở giữa là trung gian thuần tuý — chính
hệ này sinh ra nó từ DB rồi Quartz đọc lại để đổi sang HTML. Đo trên kho thật
ngày 21/08/2026: build Quartz mất 19 phút cho 4.939 trang, kéo theo 16 MB
`quartz/`, 91 gói npm và `contentIndex.json` 16,77 MB mà ba bên cùng parse.
Sinh thẳng thì bỏ được tất cả những thứ đó.

HỢP ĐỒNG URL — KHÔNG ĐƯỢC PHÁ. Quartz ghi `{slug}.html` rồi máy chủ phục vụ ở
URL không đuôi. Các URL `/van-ban/*` ĐÃ IN trong báo cáo PDF phát cho khách, nên
bố cục file phải giữ y nguyên:

    van-ban/{slug}.html      → /van-ban/{slug}
    van-ban/index.html       → /van-ban/
    bieu-mau/{slug}.html     → /bieu-mau/{slug}
    nganh/{ma}-{ten}.html    → /nganh/{ma}-{ten}
    dia-ban/{ma}.html        → /dia-ban/{ma}
    nam/{nam}.html           → /nam/{nam}
    index.html               → /          (ứng dụng tra cứu, chép từ tro-ly/)
    404.html                 → trang lỗi

CSS nằm ở MỘT file `static/trang.css` chứ không nhúng vào từng trang: nhúng vào
4.939 trang là 4.939 bản sao của cùng một khối, và trình duyệt mất luôn khả năng
cache giữa các trang.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import text

from src.legal import effectivity
from src.legal.hierarchy import LEVEL_NON_NORMATIVE, classify
from src.legal.provinces import province_name
from src.obsidian.config_obsidian import HIERARCHY_LABELS
from src.obsidian.vsic import BY_CODE
from src.publish import site_exporter
from src.storage.models import Document, DocumentReference, LegalForm, LegalFormRef

TEN_TRANG = "Tra cứu pháp lý"

# SVG nội tuyến thay cho emoji: khung trang không được phụ thuộc font emoji của
# hệ điều hành. Đo trên Chromium không cài font emoji: ⚖ và ◐ ra ô vuông, mà đó
# đúng là hai thứ nằm ở góc trên bên trái — chỗ nhìn đầu tiên.
LOGO = ('<svg viewBox="0 0 24 24" width="15" height="15" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        'aria-hidden="true"><path d="M12 3v18M7 21h10M5 7h14M5 7l-3 6h6zM19 7l3 6h-6z"/>'
        '</svg>')
ICON_NEN = ('<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" '
            'aria-hidden="true"><path d="M12 2a10 10 0 000 20z"/>'
            '<circle cx="12" cy="12" r="9.2" fill="none" stroke="currentColor" '
            'stroke-width="1.6"/></svg>')
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
           "viewBox='0 0 24 24'%3E%3Crect width='24' height='24' rx='5' "
           "fill='%23529cca'/%3E%3Cpath d='M12 5v14M8 19h8M6 9h12' stroke='%23fff' "
           "stroke-width='1.9' stroke-linecap='round' fill='none'/%3E%3C/svg%3E")

# ── Vỏ trang ────────────────────────────────────────────────────────────────

CSS = """\
/* Bảng màu TỐI là mặc định, giống trang trợ lý — hai trang phải trông như một
   hệ, không phải hai sản phẩm ghép lại. Mọi biến màu đều khai ở CẢ HAI khối:
   thiếu một biến ở khối sáng là một chỗ dùng màu tối trên nền sáng, mà bảng ít
   dùng luôn là bảng lặng lẽ hỏng. */
:root{
  color-scheme:dark;
  --nen:#191919; --nen-2:#202020; --nen-3:#2c2c2c;
  --chu:#d4d4d4; --chu-2:#9b9b9b; --chu-3:#6f6f6f;
  --vien:#2f2f2f; --nhan:#529cca; --nhan-nen:rgba(82,156,202,.16);
  --ok-nen:#2d3d33; --ok:#4dab9a;
  --xau-nen:#522e2a; --xau:#ff7369;
  --canh-nen:#59563b; --canh:#ffdc49;
  --tin-nen:#2b4661; --tin:#5aa9e6;
  --xam-nen:#373737; --xam:#9b9b9b;
  --chu-font:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  --mono:"SFMono-Regular",Menlo,Consolas,"Liberation Mono",monospace;
}
:root[data-theme=light]{
  color-scheme:light;
  --nen:#fff; --nen-2:#f7f7f5; --nen-3:#f1f1ef;
  --chu:#37352f; --chu-2:#787774; --chu-3:#9b9a97;
  --vien:#e9e9e7; --nhan:#1868b7; --nhan-nen:rgba(35,131,226,.13);
  --ok-nen:#dbeddb; --ok:#28553a;
  --xau-nen:#fbe4e4; --xau:#8a3a37;
  --canh-nen:#fbf3db; --canh:#6b5518;
  --tin-nen:#ddebf1; --tin:#1c4d63;
  --xam-nen:#f1f1ef; --xam:#5f5e5b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--nen);color:var(--chu);font-family:var(--chu-font);
  font-size:15px;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:var(--nhan);text-underline-offset:.15em}
code{font-family:var(--mono);font-size:.88em;background:var(--nen-3);
  padding:.1em .32em;border-radius:3px}

.thanh{position:sticky;top:0;z-index:5;background:var(--nen-2);
  border-bottom:1px solid var(--vien);padding:.55rem 1rem;display:flex;
  gap:1rem;align-items:center;flex-wrap:wrap}
.thanh a.ten{font-weight:600;color:var(--chu);text-decoration:none;white-space:nowrap;display:inline-flex;align-items:center;gap:.4rem}
button.chu-de{display:inline-flex;align-items:center}
.thanh .tim{margin-left:auto}
.thanh input{background:var(--nen);border:1px solid var(--vien);border-radius:5px;
  color:var(--chu);padding:.35rem .6rem;font:inherit;font-size:.86rem;min-width:15rem}
button.chu-de{background:none;border:1px solid var(--vien);border-radius:5px;
  color:var(--chu-2);cursor:pointer;padding:.3rem .55rem;font:inherit;font-size:.82rem}
button.chu-de:hover{background:var(--nen-3)}

main{max-width:52rem;margin:0 auto;padding:1.5rem 1rem 4rem}
.duong{font-size:.8rem;color:var(--chu-3);margin-bottom:.9rem}
.duong a{color:var(--chu-2)}
h1{font-size:1.5rem;line-height:1.3;margin:.2rem 0 .7rem;text-wrap:balance}
h2{font-size:1.05rem;margin:2.2rem 0 .6rem;padding-bottom:.3rem;
  border-bottom:1px solid var(--vien)}
.sh{font-family:var(--mono);font-size:.82rem;color:var(--nhan);margin-bottom:.15rem}

.the{display:inline-block;font-size:.74rem;padding:.14rem .5rem;border-radius:3px;
  margin:0 .3rem .3rem 0;white-space:nowrap}
.the.ok{background:var(--ok-nen);color:var(--ok)}
.the.xau{background:var(--xau-nen);color:var(--xau)}
.the.canh{background:var(--canh-nen);color:var(--canh)}
.the.tin{background:var(--tin-nen);color:var(--tin)}
.the.xam{background:var(--xam-nen);color:var(--xam)}

.cuon{overflow-x:auto;margin:.8rem 0}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{padding:.45rem .7rem;text-align:left;border-bottom:1px solid var(--vien);
  vertical-align:top}
thead th{background:var(--nen-3);font-size:.76rem;text-transform:uppercase;
  letter-spacing:.05em;color:var(--chu-2);white-space:nowrap}
td.so,th.so{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;
  font-family:var(--mono)}
tbody tr:last-child td{border-bottom:0}
table.dk th{width:12rem;color:var(--chu-2);font-weight:500}

.luu{border-left:3px solid var(--vien);background:var(--nen-2);padding:.7rem .9rem;
  margin:1rem 0;font-size:.86rem;color:var(--chu-2);border-radius:0 4px 4px 0}
.luu b{color:var(--chu);display:block;margin-bottom:.2rem}
.luu.canh{border-left-color:var(--canh)}
ul{padding-left:1.15rem}
li{margin-bottom:.3rem}
.trong{color:var(--chu-3);font-style:italic}
footer{border-top:1px solid var(--vien);margin-top:3rem;padding:1.2rem 1rem;
  font-size:.8rem;color:var(--chu-3);text-align:center}
"""

# `tim.js` chỉ làm hai việc: nhớ bảng màu, và đưa ô tìm kiếm về trang chủ (nơi
# đã có sẵn chỉ mục tra cứu). KHÔNG dựng lại công cụ tìm kiếm ở đây — bộ chỉ mục
# 1,9 MB đã nằm ở trang chủ, nhân bản nó ra 4.939 trang là quay lại đúng cái
# contentIndex.json 16,77 MB vừa bỏ đi.
JS = """\
(function(){
  var k='troly.theme';
  try{ if(localStorage.getItem(k)==='light') document.documentElement.dataset.theme='light'; }catch(e){}
  document.addEventListener('click',function(e){
    var b=e.target.closest('.chu-de'); if(!b) return;
    var sang=document.documentElement.dataset.theme!=='light';
    document.documentElement.dataset.theme=sang?'light':'dark';
    try{ localStorage.setItem(k,sang?'light':'dark'); }catch(e){}
  });
  var f=document.getElementById('tim');
  if(f) f.addEventListener('submit',function(e){
    e.preventDefault();
    var q=f.querySelector('input').value.trim();
    location.href=f.dataset.goc+(q?'?q='+encodeURIComponent(q):'');
  });
})();
"""


def e(s) -> str:
    """Thoát HTML. Mọi thứ lấy từ DB đều đi qua đây — tiêu đề văn bản có chứa
    dấu ngoặc kép và ký tự & thật, không phải dữ liệu sạch."""
    return html.escape(str(s if s is not None else ""), quote=True)


@dataclass
class ThongKeHtml:
    van_ban: int = 0
    bieu_mau: int = 0
    chi_muc: int = 0
    tinh: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _vo(tieu_de: str, than: str, sau: int, mo_ta: str = "") -> str:
    """Vỏ HTML chung. `sau` là độ sâu thư mục để tính đường dẫn tương đối."""
    goc = "../" * sau if sau else ""
    md = f'<meta name="description" content="{e(mo_ta)}">' if mo_ta else ""
    return f"""<!doctype html>
<html lang="vi"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(tieu_de)} · {e(TEN_TRANG)}</title>{md}
<link rel="stylesheet" href="{goc}static/trang.css">
<link rel="icon" href="{FAVICON}">
</head><body>
<nav class="thanh">
  <a class="ten" href="{goc}">{LOGO} {e(TEN_TRANG)}</a>
  <form class="tim" id="tim" data-goc="{goc}"><input type="search"
    placeholder="Tra số hiệu, tên văn bản…" aria-label="Tìm kiếm"></form>
  <button class="chu-de" type="button" aria-label="Đổi nền sáng/tối">{ICON_NEN}</button>
</nav>
<main>
{than}
</main>
<footer>
  Bản sao không chính thức · dữ kiện phục vụ kiểm chứng ·
  <a href="https://vbpl.vn">Nguồn Bộ Tư pháp</a>
</footer>
<script src="{goc}static/tim.js"></script>
</body></html>
"""


# ── Mảnh nội dung ───────────────────────────────────────────────────────────

_KIEU_HL = {
    "con_hieu_luc": "ok", "het_toan_bo": "xau", "het_hieu_luc": "xau",
    "het_mot_phan": "canh", "can_kiem_tra": "canh", "co_ban_thay_the": "canh",
    "chua_hieu_luc": "tin", "khong_ro": "xam",
}


def _the_hl(ma: str) -> str:
    return (f'<span class="the {_KIEU_HL.get(ma, "xam")}">'
            f'{e(effectivity.label(ma))}</span>')


def _bang_tac_dong(rows: list[dict]) -> str:
    if not rows:
        return ('<p class="trong">Chưa chấm điểm tác động cho văn bản này — có thể '
                'vì nó không chứa mệnh đề ràng buộc nào (thông báo, công điện), '
                'hoặc chưa được đưa vào chỉ mục.</p>')
    hang = "\n".join(
        f'<tr><td>{e(BY_CODE.get(r["vsic_code"], {}).get("ten_ngan", r["vsic_code"]))} '
        f'({e(r["vsic_code"])})</td>'
        f'<td class="so">{r["impact_pct_doc"]:.1f}%</td>'
        f'<td class="so">{r["impact_pct_industry"]:.0f}</td></tr>'
        for r in rows
    )
    return f"""<div class="luu"><b>Chỉ số này đo cường độ quy phạm, KHÔNG đo chi phí kinh tế.</b>
Số lượng và mức độ cưỡng chế của các mệnh đề ràng buộc, nhân với mức liên quan tới
ngành, có trọng số theo cấp hiệu lực pháp lý. Cách tính: xem <code>src/analysis/</code>.</div>
<div class="cuon"><table>
<thead><tr><th>Ngành (VSIC cấp 1)</th><th class="so">Tỷ trọng</th><th class="so">Cường độ</th></tr></thead>
<tbody>{hang}</tbody></table></div>"""


def _lien_quan(session, doc: Document, slug_theo_so: dict[str, str]) -> str:
    """Dẫn chiếu hai chiều. Số hiệu chưa có trang thì hiện dạng chữ kèm ghi chú —
    link tới trang không tồn tại tệ hơn hẳn không có link, vì người đọc bấm vào
    mới biết, và đây đúng là chỗ họ bấm để kiểm chứng căn cứ."""
    ra: list[str] = []

    di = session.query(DocumentReference).filter(
        DocumentReference.source_doc_id == doc.id).all()
    if di:
        muc = []
        for r in di:
            dich = (r.target_doc_num or "").strip()
            if dich in site_exporter.JUNK_TARGETS:
                continue
            slug = slug_theo_so.get(dich)
            lk = (f'<a href="{e(slug)}">{e(dich)}</a>' if slug
                  else f'<code>{e(dich)}</code> <span class="trong">(chưa có trong kho)</span>')
            muc.append(f"<li>{e(r.relation_type)}: {lk}</li>")
        if muc:
            ra.append("<p><b>Văn bản này dẫn chiếu tới:</b></p><ul>"
                      + "".join(muc) + "</ul>")

    den = session.query(DocumentReference).filter(
        DocumentReference.target_doc_num == doc.doc_num).all()
    if den:
        muc = []
        for r in den:
            src = session.query(Document).filter(Document.id == r.source_doc_id).first()
            if not src:
                continue
            slug = slug_theo_so.get(src.doc_num)
            lk = (f'<a href="{e(slug)}">{e(src.doc_num)}</a>' if slug
                  else f"<code>{e(src.doc_num)}</code>")
            muc.append(f"<li>{e(r.relation_type)} bởi {lk}</li>")
        if muc:
            ra.append("<p><b>Bị các văn bản sau tác động:</b></p><ul>"
                      + "".join(muc) + "</ul>")

    return "".join(ra) or '<p class="trong">Chưa ghi nhận văn bản liên quan.</p>'


def _bieu_mau_kem(session, doc: Document) -> str:
    rows = (
        session.query(LegalForm)
        .join(LegalFormRef, LegalFormRef.form_key == LegalForm.form_key)
        .filter(LegalFormRef.doc_key == doc.doc_key)
        .filter(LegalForm.is_business.is_(True))
        .filter(LegalForm.public_slug.isnot(None))
        .order_by(LegalForm.title)
        .all()
    )
    if not rows:
        return '<p class="trong">Chưa ghi nhận biểu mẫu nào kèm theo văn bản này.</p>'
    return "<ul>" + "".join(
        f'<li><a href="../bieu-mau/{e(f.public_slug)}">'
        f'{e(site_exporter._short(f.title or f.form_key, 90))}</a></li>'
        for f in rows
    ) + "</ul>"


def _nguon(doc: Document) -> str:
    muc = []
    if doc.gdrive_fulltext_link:
        muc.append(f'<li><b>Toàn văn (bản kho giữ):</b> '
                   f'<a href="{e(doc.gdrive_fulltext_link)}" rel="noopener">mở trên Google Drive</a></li>')
    if doc.gdrive_docx_link:
        muc.append(f'<li>Bản .docx: <a href="{e(doc.gdrive_docx_link)}" rel="noopener">tải về</a></li>')
    if not doc.gdrive_fulltext_link:
        muc.append('<li class="trong">Kho chưa có bản toàn văn của văn bản này. '
                   'Các địa chỉ dưới đây là nơi ĐỐI CHIẾU nguồn, không phải nơi đọc.</li>')
    if doc.moj_url:
        muc.append(f'<li>Bản ghi gốc trên hệ thống Bộ Tư pháp '
                   f'<span class="trong">(dữ liệu JSON, không phải trang đọc)</span>: '
                   f'<a href="{e(doc.moj_url)}" rel="noopener">{e(doc.moj_url)}</a></li>')
    if doc.tvpl_url:
        muc.append(f'<li>Trang Thư viện Pháp luật: '
                   f'<a href="{e(doc.tvpl_url)}" rel="noopener">{e(doc.tvpl_url)}</a></li>')
    if not muc:
        muc.append('<li class="trong">Chưa ghi nhận được địa chỉ nguồn cho văn bản này.</li>')
    return "<ul>" + "".join(muc) + "</ul>"


# ── Trang văn bản ───────────────────────────────────────────────────────────

def trang_van_ban(session, doc: Document, tac_dong: list[dict],
                  slug_theo_so: dict[str, str]) -> str:
    cap = LEVEL_NON_NORMATIVE if doc.hierarchy_level is None else int(doc.hierarchy_level)
    tt = doc.eff_state or effectivity.KHONG_RO
    pv = doc.territorial_scope or "khong_xac_dinh"
    tinh = province_name(doc.province_code_current)
    if pv == "tinh":
        nhan_pv = f"Địa phương — {tinh}" if tinh else "Địa phương (chưa rõ tỉnh)"
    elif pv == "trung_uong":
        nhan_pv = "Toàn quốc"
    else:
        nhan_pv = "Chưa xác định"

    cq = doc.agency_name or classify(doc.doc_num or "", doc.doc_type or "", "").agency \
        or "Chưa xác định"

    ngu_canh = ""
    if doc.is_closure_node:
        ngu_canh = ('<div class="luu canh"><b>Văn bản ngữ cảnh</b>'
                    'Bản này có trong kho vì được văn bản khác dẫn chiếu tới, không '
                    'phải vì thuộc phạm vi theo dõi. Xem tình trạng hiệu lực bên dưới '
                    'trước khi dùng.</div>')

    than = f"""<div class="duong"><a href="../">Trang chủ</a> ›
  <a href="./">Văn bản</a> › {e(doc.doc_num)}</div>
<div class="sh">{e(doc.doc_num)}</div>
<h1>{e(doc.title or doc.doc_num)}</h1>
<div>{_the_hl(tt)}<span class="the tin">{e(HIERARCHY_LABELS.get(cap, HIERARCHY_LABELS[LEVEL_NON_NORMATIVE]))}</span>
  <span class="the xam">{e(nhan_pv)}</span></div>

<div class="luu"><b>Bản sao không chính thức</b>
Trang này là bản trích dữ kiện phục vụ tra cứu và kiểm chứng nguồn. Bản có giá trị
pháp lý là bản công bố trên hệ thống của cơ quan nhà nước — xem mục <i>Nguồn gốc</i>.
Trang này không đăng toàn văn.</div>
{ngu_canh}
<h2>Dữ kiện</h2>
<div class="cuon"><table class="dk"><tbody>
<tr><th>Số hiệu</th><td><code>{e(doc.doc_num)}</code></td></tr>
<tr><th>Loại văn bản</th><td>{e(doc.doc_type or "—")}</td></tr>
<tr><th>Cấp hiệu lực pháp lý</th><td>{e(HIERARCHY_LABELS.get(cap, HIERARCHY_LABELS[LEVEL_NON_NORMATIVE]))}</td></tr>
<tr><th>Cơ quan ban hành</th><td>{e(cq)}</td></tr>
<tr><th>Phạm vi áp dụng</th><td>{e(nhan_pv)}</td></tr>
<tr><th>Ngày ban hành</th><td>{e(doc.issue_date or "—")}</td></tr>
<tr><th>Ngày có hiệu lực</th><td>{e(doc.eff_from or "—")}</td></tr>
<tr><th>Tình trạng hiệu lực</th><td>{e(effectivity.label(tt))}
  <span class="trong">(tính đến {e(doc.eff_state_as_of or "—")})</span></td></tr>
</tbody></table></div>

<h2>Mức độ tác động theo ngành</h2>
{_bang_tac_dong(tac_dong)}

<h2>Văn bản liên quan</h2>
{_lien_quan(session, doc, slug_theo_so)}

<h2>Biểu mẫu kèm theo</h2>
{_bieu_mau_kem(session, doc)}

<h2>Nguồn gốc</h2>
{_nguon(doc)}"""
    return _vo(f"{doc.doc_num} — {site_exporter._short(doc.title or '', 60)}",
               than, sau=1, mo_ta=site_exporter._short(doc.title or "", 150))


# ── Trang chỉ mục ───────────────────────────────────────────────────────────

def _bang_danh_sach(docs, sau: int) -> str:
    if not docs:
        return '<p class="trong">Chưa có văn bản nào trong nhóm này.</p>'
    hang = "\n".join(
        f'<tr><td><a href="{"../" * (sau - 1) if sau > 1 else ""}van-ban/{e(d.public_slug)}">'
        f'<code>{e(d.doc_num)}</code></a></td>'
        f'<td>{e(site_exporter._short(d.title or "", 110))}</td>'
        f'<td>{e(d.agency_name or "—")}</td>'
        f'<td class="so">{e(d.issue_date or "—")}</td>'
        f'<td>{_the_hl(d.eff_state or effectivity.KHONG_RO)}</td></tr>'
        for d in docs
    )
    return f"""<div class="cuon"><table>
<thead><tr><th>Số hiệu</th><th>Tên văn bản</th><th>Cơ quan</th>
<th class="so">Ban hành</th><th>Hiệu lực</th></tr></thead>
<tbody>{hang}</tbody></table></div>"""


def trang_chi_muc(tieu_de: str, dan_nhap: str, docs, sau: int = 1) -> str:
    than = (f'<div class="duong"><a href="{"../" * sau}">Trang chủ</a> › {e(tieu_de)}</div>'
            f"<h1>{e(tieu_de)}</h1>"
            f"<p>{dan_nhap}</p>"
            f"<p><b>{len(docs)}</b> văn bản.</p>"
            + _bang_danh_sach(docs, sau))
    return _vo(tieu_de, than, sau=sau)


# ── Bộ điều phối ────────────────────────────────────────────────────────────

def _ghi(duong: Path, noi_dung: str) -> None:
    duong.parent.mkdir(parents=True, exist_ok=True)
    duong.write_text(noi_dung, encoding="utf-8")


def _slug_chi_muc(ten: str) -> str:
    """Cùng quy tắc với moc_static._slug — hai bên phải ra y hệt, vì URL
    /nganh/* đã tồn tại và không được đổi."""
    import unicodedata
    s = ten.replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s


def xuat_tai_nguyen(out_dir: Path) -> None:
    """CSS + JS dùng chung. MỘT bản cho cả site, không nhúng vào từng trang."""
    _ghi(out_dir / "static" / "trang.css", CSS)
    _ghi(out_dir / "static" / "tim.js", JS)


def xuat_404(out_dir: Path) -> None:
    than = ('<h1>Không tìm thấy trang</h1>'
            '<p>Đường dẫn này không có trong kho. Có thể văn bản chưa được đưa vào, '
            'hoặc số hiệu đã đổi.</p>'
            '<p><a href="./">Về trang tra cứu</a></p>')
    # sau=0: 404 phục vụ ở MỌI độ sâu nên không dùng được đường dẫn tương đối.
    # Dùng đường dẫn tuyệt đối theo gốc site thay thế.
    _ghi(out_dir / "404.html", _vo("Không tìm thấy", than, sau=0))


def xuat_sitemap(out_dir: Path, goc_url: str, slugs: list[str]) -> None:
    """sitemap.xml — thay cho plugin content-index của Quartz."""
    goc = goc_url.rstrip("/")
    muc = "".join(f"<url><loc>{html.escape(goc)}/{html.escape(s)}</loc></url>"
                  for s in slugs)
    _ghi(out_dir / "sitemap.xml",
         '<?xml version="1.0" encoding="UTF-8"?>'
         '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
         f"{muc}</urlset>")


def xuat_van_ban(session, out_dir: Path, version: str) -> tuple[int, list[str]]:
    """Ghi trang cho từng văn bản. Trả về (số trang, danh sách slug đầy đủ).

    Bộ lọc PHẢI trùng với bảng tra slug, nếu không sẽ tái lập đúng lỗi F3: slug
    phân giải được nhưng trang không bao giờ được ghi, sinh ra link chết.
    """
    slug_theo_so = site_exporter.build_slug_index(session)
    tac_dong = site_exporter.impacts_by_doc(session, version)

    docs = (session.query(Document)
            .filter(Document.is_vbqppl == True)  # noqa: E712
            .order_by(Document.id).all())

    n, duong_dan = 0, []
    for doc in docs:
        if (doc.doc_num or "").strip() in site_exporter.JUNK_TARGETS or not doc.public_slug:
            continue
        _ghi(out_dir / "van-ban" / f"{doc.public_slug}.html",
             trang_van_ban(session, doc, tac_dong.get(doc.doc_key, []), slug_theo_so))
        duong_dan.append(f"van-ban/{doc.public_slug}")
        n += 1
    return n, duong_dan


def xuat_chi_muc(session, out_dir: Path, version: str) -> tuple[int, list[str]]:
    """Chỉ mục theo ngành VSIC, địa bàn và năm — cùng bố cục URL với bản Quartz."""
    from collections import defaultdict

    from src.obsidian.vsic import VSIC_LEVEL1

    docs = (session.query(Document)
            .filter(Document.is_vbqppl == True)  # noqa: E712
            .filter(Document.public_slug.isnot(None))
            .filter((Document.is_closure_node.is_(None))
                    | (Document.is_closure_node == False))  # noqa: E712
            .order_by(Document.issue_date.desc()).all())
    docs = [d for d in docs
            if (d.doc_num or "").strip() not in site_exporter.JUNK_TARGETS]
    theo_key = {d.doc_key: d for d in docs}

    dau_nganh = session.execute(text("""
        SELECT doc_key, vsic_code FROM (
            SELECT doc_key, vsic_code,
                   ROW_NUMBER() OVER (PARTITION BY doc_key ORDER BY impact_pct_doc DESC) rn
            FROM document_industry_impact WHERE scorer_version = :v
        ) WHERE rn = 1
    """), {"v": version}).mappings().all()

    theo_nganh: dict[str, list] = defaultdict(list)
    for r in dau_nganh:
        d = theo_key.get(r["doc_key"])
        if d:
            theo_nganh[r["vsic_code"]].append(d)

    n, duong_dan = 0, []
    for ng in VSIC_LEVEL1:
        ma = ng["ma"]
        ten_file = f"{ma}-{_slug_chi_muc(ng['ten_ngan'])}"
        _ghi(out_dir / "nganh" / f"{ten_file}.html",
             trang_chi_muc(f"Ngành {ma} — {ng['ten_ngan']}",
                           "Văn bản có tác động lớn nhất tới ngành này "
                           "(VSIC cấp 1, theo Quyết định 27/2018/QĐ-TTg).",
                           theo_nganh.get(ma, [])))
        duong_dan.append(f"nganh/{ten_file}")
        n += 1

    theo_tinh: dict[str, list] = defaultdict(list)
    for d in docs:
        if d.territorial_scope == "tinh" and d.province_code_current:
            theo_tinh[d.province_code_current].append(d)
    for ma, nhom in sorted(theo_tinh.items()):
        _ghi(out_dir / "dia-ban" / f"{ma}.html",
             trang_chi_muc(province_name(ma) or ma,
                           "Văn bản do cơ quan địa phương ban hành.", nhom))
        duong_dan.append(f"dia-ban/{ma}")
        n += 1

    theo_nam: dict[int, list] = defaultdict(list)
    for d in docs:
        if d.issue_date:
            theo_nam[d.issue_date.year].append(d)
    for nam, nhom in sorted(theo_nam.items(), reverse=True):
        _ghi(out_dir / "nam" / f"{nam}.html",
             trang_chi_muc(f"Năm {nam}", "Văn bản ban hành trong năm.", nhom))
        duong_dan.append(f"nam/{nam}")
        n += 1

    _ghi(out_dir / "van-ban" / "index.html",
         trang_chi_muc("Toàn bộ văn bản trong danh mục",
                       "Văn bản nghiệp vụ. Văn bản ngữ cảnh có trang riêng nhưng "
                       "không liệt kê ở đây.", docs))
    duong_dan.append("van-ban/")
    n += 1
    return n, duong_dan


def xuat_site(session, out_dir: Path, version: str,
              goc_url: str = "", tro_ly_dir: Path | None = None) -> ThongKeHtml:
    """Dựng toàn bộ trang tĩnh. Không dùng Node, không dùng Quartz."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tk = ThongKeHtml()

    xuat_tai_nguyen(out_dir)
    # SLUG BIỂU MẪU TRƯỚC TIÊN. Mục "Biểu mẫu kèm theo" trên trang văn bản chỉ
    # liệt kê mẫu đã có slug, nên đảo thứ tự là mọi trang văn bản ghi "chưa ghi
    # nhận biểu mẫu nào" dù quan hệ đã có trong kho.
    gan_slug_bieu_mau(session)
    tk.bieu_mau, dd_bm = xuat_bieu_mau(session, out_dir)
    tk.van_ban, dd_vb = xuat_van_ban(session, out_dir, version)
    tk.chi_muc, dd_cm = xuat_chi_muc(session, out_dir, version)
    xuat_404(out_dir)

    # Trang chủ là ứng dụng tra cứu, chép nguyên từ tro-ly/.
    if tro_ly_dir and (tro_ly_dir / "index.html").exists():
        for ten in ("index.html", "du-lieu.json"):
            nguon = tro_ly_dir / ten
            if nguon.exists():
                _ghi(out_dir / ten, nguon.read_text(encoding="utf-8"))
        # Giữ /tro-ly/ sống bằng một trang chuyển hướng. Địa chỉ đó đã được chia
        # sẻ khi trợ lý còn nằm ở thư mục con; để nó 404 là làm chết link người
        # khác đang giữ, mà thay bằng 3 dòng thì không tốn gì. KHÔNG chép lại
        # du-lieu.json 1,9 MB lần hai — chỉ chuyển hướng.
        _ghi(out_dir / "tro-ly" / "index.html",
             '<!doctype html><html lang="vi"><head><meta charset="utf-8">'
             "<title>Đã chuyển về trang chủ</title>"
             '<link rel="canonical" href="../">'
             '<meta http-equiv="refresh" content="0; url=../"></head>'
             "<body><p>Trang trợ lý nay là trang chủ — "
             '<a href="../">mở tại đây</a>.</p></body></html>\n')

    if goc_url:
        xuat_sitemap(out_dir, goc_url, [""] + dd_vb + dd_bm + dd_cm)
    tk.tinh = 2
    return tk


# ── Trang biểu mẫu ──────────────────────────────────────────────────────────

_KIEU_BM = {
    "con_hieu_luc": "ok", "co_ban_thay_the": "canh", "can_kiem_tra": "canh",
    "het_hieu_luc": "xau", "khong_ro": "xam",
}


def trang_bieu_mau(session, form: LegalForm, slug_theo_so: dict[str, str]) -> str:
    """Một biểu mẫu. Khối hiệu lực đặt NGAY DƯỚI tiêu đề, trước cả link tải.

    Một biểu mẫu hết hiệu lực trông y hệt một biểu mẫu còn dùng được, và người
    tải về không có cách nào tự biết. Đặt cảnh báo dưới phần nội dung nghĩa là
    phần lớn người đọc tải file xong mới thấy — tức không thấy.
    """
    import json

    from src.forms import effectivity as bm_eff
    from src.legal.form_taxonomy import NGHIEP_VU, ten_nhom_hop_dong
    from src.publish.form_exporter import public_slug_bieu_mau
    from src.publish.md_toi_gian import sang_html
    from src.sources.tvpl_forms_parse import SOURCE_HOP_DONG

    tt = form.eff_state or bm_eff.KHONG_RO
    kieu = _KIEU_BM.get(tt, "xam")

    go = ""
    if form.delisted_at:
        go = (f'<div class="luu canh"><b>Nguồn đã gỡ biểu mẫu này</b>'
              f'Thư viện Pháp luật không còn liệt kê biểu mẫu này (phát hiện ngày '
              f'{form.delisted_at:%d/%m/%Y}). Thường là vì văn bản kèm theo đã bị '
              f'thay thế. Bản dưới đây giữ lại để tra cứu, KHÔNG nên dùng để nộp.</div>')

    hl = [f'<div class="luu"><b>{e(bm_eff.NHAN.get(tt, bm_eff.NHAN[bm_eff.KHONG_RO]))}</b>']
    if form.eff_note:
        hl.append(f"{e(form.eff_note)}<br>")
    try:
        thay = json.loads(form.eff_replaced_by or "[]")
    except ValueError:
        thay = []
    if thay:
        hl.append(f"<b>Tìm biểu mẫu mới ở:</b> {e(', '.join(thay))}<br>")
    hl.append("Biểu mẫu là phụ lục kèm theo văn bản quy phạm nên hiệu lực của nó "
              "theo hiệu lực của văn bản đó — nguồn KHÔNG công bố dữ kiện này, "
              "nó được suy từ căn cứ.")
    if form.eff_state_as_of:
        hl.append(f' <span class="trong">(tính đến {form.eff_state_as_of:%d/%m/%Y})</span>')
    hl.append("</div>")

    # Tải về: DOCX trước, vì biểu mẫu là để ĐIỀN và PDF không điền được.
    tai = []
    if form.gdrive_docx_link:
        tai.append(f'<li><b><a href="{e(form.gdrive_docx_link)}" rel="noopener">'
                   f'Bản Word (.docx) — điền được</a></b> <span class="trong">'
                   f'(Google Drive)</span></li>')
    elif form.docx_path:
        tai.append(f'<li><b><a href="{e(Path(form.docx_path).name)}" download>'
                   f'Bản Word (.docx) — điền được</a></b></li>')
    if form.pdf_path:
        tai.append(f'<li><a href="{e(Path(form.pdf_path).name)}" download>'
                   f'Bản PDF — để in</a></li>')
    if form.gdrive_docx_link and form.docx_path:
        tai.append(f'<li class="trong">Bản lưu trong kho trang: '
                   f'<a href="{e(Path(form.docx_path).name)}" download>'
                   f'{e(Path(form.docx_path).name)}</a> — dùng khi link Drive '
                   f'ở trên không mở được.</li>')
    khoi_tai = ("<ul>" + "".join(tai) + "</ul>" if tai else
                '<p class="trong">Chưa dựng được file tải về cho biểu mẫu này. '
                'Nội dung đầy đủ vẫn ở phần dưới.</p>')

    # Phân loại
    meta = []
    if form.source == SOURCE_HOP_DONG and form.form_type_code:
        meta.append(f"<li><b>Nhóm hợp đồng:</b> {e(ten_nhom_hop_dong(form.form_type_code))}</li>")
    else:
        if form.field_name:
            meta.append(f"<li><b>Lĩnh vực:</b> {e(form.field_name)}</li>")
        if form.form_type_name:
            meta.append(f"<li><b>Loại mẫu:</b> {e(form.form_type_name)}</li>")
    try:
        nv = json.loads(form.nghiep_vu or "[]")
    except ValueError:
        nv = []
    if nv:
        meta.append("<li><b>Nghiệp vụ:</b> "
                    + e(", ".join(NGHIEP_VU.get(m, m) for m in nv)) + "</li>")
    if form.updated_on:
        meta.append(f"<li><b>Cập nhật:</b> {form.updated_on:%d/%m/%Y}</li>")
    khoi_meta = ("<ul>" + "".join(meta) + "</ul>" if meta
                 else '<p class="trong">Chưa có thông tin phân loại.</p>')

    # Căn cứ — hiện cả căn cứ chưa có trong kho, kèm ghi chú
    refs = session.query(LegalFormRef).filter_by(form_key=form.form_key).all()
    if refs:
        muc = []
        for r in refs:
            slug = slug_theo_so.get(r.doc_num)
            muc.append(f'<li><a href="../van-ban/{e(slug)}">{e(r.doc_num)}</a></li>'
                       if slug else
                       f'<li><code>{e(r.doc_num)}</code> '
                       f'<span class="trong">(chưa có trong kho)</span></li>')
        khoi_cc = "<ul>" + "".join(muc) + "</ul>"
    else:
        khoi_cc = '<p class="trong">Nguồn không ghi căn cứ cho biểu mẫu này.</p>'

    # Nguồn
    ng = []
    if form.gdrive_docx_link:
        ng.append(f'<li><b>Bản kho giữ (Google Drive):</b> '
                  f'<a href="{e(form.gdrive_docx_link)}" rel="noopener">mở</a></li>')
    if form.url:
        ng.append(f'<li>Trang gốc trên Thư viện Pháp luật: '
                  f'<a href="{e(form.url)}" rel="noopener">{e(form.url)}</a></li>')
    khoi_ng = ("<ul>" + "".join(ng) + "</ul>" if ng else
               '<p class="trong">Chưa ghi nhận được địa chỉ nguồn.</p>')

    # Thân mẫu: Markdown đã dựng lại → HTML. TUYỆT ĐỐI không đọc body_html_path,
    # đó là HTML gốc của TVPL, chỉ dùng làm nguyên liệu nội bộ.
    than_mau = ""
    if form.body_md_path:
        p = Path(form.body_md_path)
        if p.exists():
            md = p.read_text(encoding="utf-8")
            dau = md.find("\n> Bản dựng lại")
            if dau >= 0:
                cuoi = md.find("\n\n", dau + 1)
                if cuoi > 0:
                    md = md[cuoi:]
            than_mau = sang_html(md.strip())

    than = f"""<div class="duong"><a href="../">Trang chủ</a> ›
  <a href="./">Biểu mẫu</a> › {e(form.form_key)}</div>
<div class="sh">{e(form.form_key)}</div>
<h1>{e(form.title or form.form_key)}</h1>
<div><span class="the {kieu}">{e(bm_eff.NHAN.get(tt, bm_eff.NHAN[bm_eff.KHONG_RO]))}</span></div>
{go}{"".join(hl)}
<div class="luu"><b>Bản dựng lại</b>
Ruột biểu mẫu ở đây được dựng lại theo mẫu nhà để tiện đọc, điền và in. Nội dung
biểu mẫu là phụ lục của văn bản quy phạm pháp luật. Bản có giá trị pháp lý là bản
kèm theo văn bản gốc — xem mục <i>Nguồn</i>.</div>

<h2>Tải về</h2>
{khoi_tai}

<h2>Phân loại</h2>
{khoi_meta}

<h2>Căn cứ pháp lý</h2>
{khoi_cc}

<h2>Nguồn</h2>
{khoi_ng}

<h2>Nội dung biểu mẫu</h2>
{than_mau or '<p class="trong">Chưa dựng lại được nội dung biểu mẫu này.</p>'}"""
    return _vo(site_exporter._short(form.title or form.form_key, 60), than, sau=1)


def gan_slug_bieu_mau(session) -> int:
    """Gán `public_slug` cho biểu mẫu doanh nghiệp. PHẢI chạy trước mọi bước ghi.

    Trước đây việc này nằm lẫn trong `form_exporter.export_forms()` — bộ sinh
    markdown. Bỏ nhánh markdown mà quên tách nó ra thì KHÔNG có gì gán slug nữa,
    và hỏng theo kiểu im lặng nhất có thể: mục "Biểu mẫu kèm theo" trên trang văn
    bản chỉ liệt kê mẫu ĐÃ có slug, nên mọi trang sẽ ghi "chưa ghi nhận biểu mẫu
    nào" — một câu hoàn toàn hợp lệ, không ai phát hiện ra.
    """
    from src.publish.form_exporter import public_slug_bieu_mau

    forms = (session.query(LegalForm)
             .filter(LegalForm.is_business.is_(True))
             .order_by(LegalForm.form_key).all())
    n = 0
    for f in forms:
        slug = public_slug_bieu_mau(f)
        if f.public_slug != slug:
            f.public_slug = slug
            n += 1
    session.flush()
    return n


def xuat_bieu_mau(session, out_dir: Path) -> tuple[int, list[str]]:
    """Ghi trang cho từng biểu mẫu doanh nghiệp đã đăng, kèm mục lục theo nghiệp vụ."""
    import json

    from src.legal.form_taxonomy import NGHIEP_VU
    from src.publish.form_exporter import public_slug_bieu_mau

    slug_theo_so = site_exporter.build_slug_index(session)
    forms = (session.query(LegalForm)
             .filter(LegalForm.is_business.is_(True))
             .filter(LegalForm.public_slug.isnot(None))
             .order_by(LegalForm.form_key).all())

    duong_dan = []
    for f in forms:
        _ghi(out_dir / "bieu-mau" / f"{f.public_slug}.html",
             trang_bieu_mau(session, f, slug_theo_so))
        duong_dan.append(f"bieu-mau/{f.public_slug}")

    theo_nhom: dict[str, list] = {}
    for f in forms:
        try:
            nv = json.loads(f.nghiep_vu or "[]")
        except ValueError:
            nv = []
        for ma in nv:
            theo_nhom.setdefault(ma, []).append(f)

    phan = []
    for ma, ten in NGHIEP_VU.items():
        nhom = theo_nhom.get(ma)
        if not nhom:
            continue
        muc = "".join(
            f'<li><a href="{e(public_slug_bieu_mau(f))}">'
            f'{e(site_exporter._short(f.title or f.form_key, 90))}</a></li>'
            for f in sorted(nhom, key=lambda x: (x.title or ""))
        )
        phan.append(f"<h2>{e(ten)} ({len(nhom)})</h2><ul>{muc}</ul>")

    than = (f'<div class="duong"><a href="../">Trang chủ</a> › Biểu mẫu</div>'
            f"<h1>Biểu mẫu cho doanh nghiệp</h1>"
            f"<p><b>{len(forms)}</b> biểu mẫu, xếp theo nghiệp vụ. Mỗi trang có "
            f"bản Word điền được và bản PDF để in.</p>"
            + ("".join(phan) or '<p class="trong">Chưa có biểu mẫu nào.</p>'))
    _ghi(out_dir / "bieu-mau" / "index.html", _vo("Biểu mẫu cho doanh nghiệp", than, sau=1))
    duong_dan.append("bieu-mau/")
    return len(forms), duong_dan
