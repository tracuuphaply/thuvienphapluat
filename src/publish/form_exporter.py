"""
Sinh trang tra cứu công khai cho kho biểu mẫu.

MỤC ĐÍCH khác với trang văn bản. Trang văn bản tồn tại để KIỂM CHỨNG — người đọc
báo cáo bấm vào số hiệu và thấy văn bản đó có thật. Trang biểu mẫu tồn tại để
DÙNG — chủ doanh nghiệp tìm đúng tờ giấy mình phải điền rồi tải về.

VÌ VẬY Ở ĐÂY CÓ ĐĂNG NỘI DUNG, KHÁC VỚI TRANG VĂN BẢN. Không mâu thuẫn với
nguyên tắc "không đăng toàn văn": thứ được đăng là BẢN DỰNG LẠI của chính mình
(Markdown/DOCX/PDF sinh từ src/forms/renderer.py), không phải bản HTML của Thư
viện Pháp luật. Nội dung biểu mẫu là phụ lục của văn bản quy phạm — Điều 15 Luật
Sở hữu trí tuệ loại khỏi đối tượng bảo hộ; phần không tự do là công chuyển đổi
của bên biên tập, và bản dựng lại không dùng phần đó. Mỗi trang đều mang khối ghi
nguồn kèm link ngược.

CHỈ ĐĂNG MẪU PHỤC VỤ NGƯỜI ĐỌC THẬT — doanh nghiệp hoặc cá nhân, qua
`loc_dang_cong_khai()`. Trang này là mục lục cho người phải điền giấy tờ; đăng
cả biểu quyết toán ngân sách của Kho bạc Nhà nước là phá đúng thứ phễu ba tầng
vừa lọc ra.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from src.forms import effectivity as bm_eff
from src.legal.form_taxonomy import NGHIEP_VU, ten_nhom_hop_dong
from src.publish.site_exporter import content_hash, remove_orphan_pages
from src.sources.tvpl_forms_parse import SOURCE_HOP_DONG
from src.storage.public_slug import slugify_doc_num
from src.forms.store import loc_dang_cong_khai
from src.storage.models import LegalForm, LegalFormRef

logger = logging.getLogger(__name__)

THU_MUC = "bieu-mau"

GHI_NGUON = """> **Bản dựng lại.** Trang này dựng lại nội dung biểu mẫu để tiện tra cứu, điền
> và in. Nội dung biểu mẫu là phụ lục của văn bản quy phạm pháp luật. Bản có giá
> trị pháp lý là bản kèm theo văn bản gốc — xem mục *Nguồn* bên dưới."""

PAGE_TEMPLATE = """---
title: "{short_title}"
{khoi_ngay}form_key: "{form_key}"
nguon: "{source}"
nghiep_vu: {nghiep_vu_yaml}
phan_loai: "{phan_loai}"
hieu_luc: "{hieu_luc}"
tags: {tags}
---

# {title}

{khoi_hieu_luc}

{khoi_meta}

{ghi_nguon}

## Tải về

{khoi_tai_ve}

## Căn cứ pháp lý

{khoi_can_cu}

## Nội dung biểu mẫu

{noi_dung}

## Nguồn

{khoi_nguon}
"""


@dataclass
class FormPublishStats:
    written: int = 0
    unchanged: int = 0
    skipped_no_content: int = 0
    orphan_removed: int = 0
    moc_pages: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _short(title: str, limit: int = 70) -> str:
    title = (title or "").replace('"', "'").strip()
    return title if len(title) <= limit else title[: limit - 1] + "…"


def _yaml_list(items: list[str]) -> str:
    return "[" + ", ".join(f'"{i}"' for i in items) + "]" if items else "[]"


def public_slug_bieu_mau(form: LegalForm) -> str:
    """Slug ổn định của một biểu mẫu.

    Suy TỪ CHÍNH biểu mẫu đó (kho + id TVPL), không từ tiêu đề: tiêu đề bị TVPL
    sửa chữ thường xuyên, mà URL đã phát ra trong tin nhắn Telegram và trong báo
    cáo thì không được đổi. Cùng nguyên tắc thứ nhất của src/storage/public_slug.py.
    """
    return slugify_doc_num(f"bm-{form.source}-{form.external_id}")


def _khoi_hieu_luc(form: LegalForm) -> str:
    """Khối hiệu lực, đặt NGAY DƯỚI tiêu đề.

    Đây là thông tin quan trọng nhất trên trang: một biểu mẫu hết hiệu lực trông y
    hệt một biểu mẫu còn dùng được, và người tải về không có cách nào tự biết. Đặt
    nó dưới phần nội dung nghĩa là phần lớn người đọc sẽ tải file trước khi thấy.

    Biểu mẫu bị TVPL gỡ được cảnh báo TRƯỚC hiệu lực: nguồn đã bỏ nó thì mọi suy
    luận từ căn cứ đều là suy luận trên một tờ giấy không còn tồn tại ở đâu.
    """
    dong = []
    if form.delisted_at:
        dong.append(
            f"> [!danger] Nguồn đã gỡ biểu mẫu này\n"
            f"> Thư viện Pháp luật không còn liệt kê biểu mẫu này "
            f"(phát hiện ngày {form.delisted_at:%d/%m/%Y}). Thường là vì văn bản "
            f"kèm theo đã bị thay thế. Bản dưới đây giữ lại để tra cứu, KHÔNG nên "
            f"dùng để nộp."
        )

    trang_thai = form.eff_state or bm_eff.KHONG_RO
    nhan = bm_eff.NHAN.get(trang_thai, bm_eff.NHAN[bm_eff.KHONG_RO])
    muc = {
        bm_eff.CON_HIEU_LUC: "tip",
        bm_eff.CAN_KIEM_TRA: "warning",
        bm_eff.CO_BAN_THAY_THE: "warning",
        bm_eff.HET_HIEU_LUC: "danger",
        bm_eff.KHONG_RO: "info",
    }.get(trang_thai, "info")

    khoi = [f"> [!{muc}] {nhan}"]
    if form.eff_note:
        khoi.append(f"> {form.eff_note}")
    if form.eff_replaced_by:
        try:
            ds = json.loads(form.eff_replaced_by)
        except ValueError:
            ds = []
        if ds:
            khoi.append(f"> **Tìm biểu mẫu mới ở:** {', '.join(ds)}")
    if form.eff_state_as_of:
        khoi.append(f"> *Tính đến {form.eff_state_as_of:%d/%m/%Y}. Biểu mẫu là phụ "
                    f"lục kèm theo văn bản quy phạm nên hiệu lực của nó theo hiệu "
                    f"lực của văn bản đó — nguồn KHÔNG công bố dữ kiện này.*")
    dong.append("\n".join(khoi))
    return "\n\n".join(dong)


def _khoi_meta(form: LegalForm, nghiep_vu: list[str]) -> str:
    dong = []
    if form.source == SOURCE_HOP_DONG and form.form_type_code:
        dong.append(f"- **Nhóm hợp đồng:** {ten_nhom_hop_dong(form.form_type_code)}")
    else:
        if form.field_name:
            dong.append(f"- **Lĩnh vực:** {form.field_name}")
        if form.form_type_name:
            dong.append(f"- **Loại mẫu:** {form.form_type_name}")
    if nghiep_vu:
        dong.append("- **Nghiệp vụ:** "
                    + ", ".join(NGHIEP_VU.get(m, m) for m in nghiep_vu))
    if form.updated_on:
        dong.append(f"- **Cập nhật:** {form.updated_on:%d/%m/%Y}")
    return "\n".join(dong) or "*Chưa có thông tin phân loại.*"


def _khoi_tai_ve(form: LegalForm) -> str:
    """Link tải. DOCX đứng trước: biểu mẫu là để ĐIỀN, PDF không điền được.

    Bản Word ưu tiên GOOGLE DRIVE khi đã tải lên: Drive xem trước được ngay trên
    trình duyệt và tải về được, còn file trong repo thì tuỳ trình duyệt mà mở hay
    tải.

    NHƯNG BẢN TRONG REPO VẪN PHẢI CÓ LINK, kể cả khi đã có Drive. Nó là bản dự
    phòng duy nhất nằm ngoài tầm với của một tài khoản Google — link Drive hỏng
    vì đổi quyền, quá hạn mức hay xoá nhầm thì trang mất sạch đường tải bản Word,
    mà đó chính là bản người ta cần (PDF không điền được). Có lúc `sao_chep_file_tai_ve()`
    vẫn chép đủ 653 file .docx sang repo công khai trong khi hàm này thôi trỏ tới
    chúng: 26,8 MB nằm đó không ai tới được thì không còn là bản lưu, chỉ là rác.
    Nên nó xuống dòng phụ, chữ nghiêng, nói rõ dùng khi nào — không đứng ngang
    hàng bắt người đọc phải chọn giữa hai bản y hệt nhau.
    """
    dong = []
    docx = Path(form.docx_path) if form.docx_path else None
    co_docx = bool(docx and docx.exists())
    pdf = Path(form.pdf_path) if form.pdf_path else None

    if form.gdrive_docx_link:
        dong.append(f"- [Bản Word (.docx) — điền được]({form.gdrive_docx_link}) "
                    "*(Google Drive)*")
    elif co_docx:
        dong.append(f"- [Bản Word (.docx) — điền được](./{docx.name})")
    if pdf and pdf.exists():
        dong.append(f"- [Bản PDF — để in](./{pdf.name})")
    if form.gdrive_docx_link and co_docx:
        dong.append(f"- *Bản lưu trong kho trang: [{docx.name}](./{docx.name}) "
                    "— dùng khi link Drive ở trên không mở được.*")

    if not dong:
        return ("*Chưa dựng được file tải về cho biểu mẫu này. "
                "Nội dung đầy đủ vẫn ở phần dưới.*")
    return "\n".join(dong)


def _khoi_nguon(form: LegalForm) -> str:
    """Bản kho tự giữ đứng trước, trang gốc đứng sau.

    Trước đây mục này chỉ có một dòng trỏ về Thư viện Pháp luật — tức đẩy người
    đọc ra khỏi kho của mình, tới một trang có tường Cloudflare và có thể đổi
    hoặc gỡ mẫu bất cứ lúc nào. Trang gốc vẫn giữ, vì ghi nguồn là việc phải làm;
    nhưng nó không còn là đường DUY NHẤT để lấy biểu mẫu.
    """
    dong = []
    if form.gdrive_docx_link:
        dong.append(f"- **Bản kho giữ (Google Drive):** <{form.gdrive_docx_link}>")
    if form.url:
        dong.append(f"- Trang gốc trên Thư viện Pháp luật: <{form.url}>")
    if not dong:
        dong.append("- *Chưa ghi nhận được địa chỉ nguồn cho biểu mẫu này.*")
    return "\n".join(dong)


def _khoi_can_cu(session, form: LegalForm, slug_by_num: dict[str, str]) -> str:
    """Căn cứ, nối wikilink sang trang văn bản khi kho đã có.

    Căn cứ chưa có trong kho vẫn HIỆN RA kèm ghi chú, không bị giấu đi: người đọc
    cần biết biểu mẫu này dựa trên văn bản nào, kể cả khi mình chưa có văn bản đó.
    """
    refs = session.query(LegalFormRef).filter_by(form_key=form.form_key).all()
    if not refs:
        return "*Nguồn không ghi căn cứ cho biểu mẫu này.*"
    dong = []
    for r in refs:
        slug = slug_by_num.get(r.doc_num)
        if slug:
            dong.append(f"- [[{slug}|{r.doc_num}]]")
        else:
            dong.append(f"- `{r.doc_num}` *(chưa có trong kho)*")
    return "\n".join(dong)


def _noi_dung(form: LegalForm) -> str:
    """Thân biểu mẫu, lấy từ bản Markdown ĐÃ DỰNG LẠI.

    Tuyệt đối không đọc từ `body_html_path`: đó là HTML gốc của Thư viện Pháp
    luật, chỉ dùng làm nguyên liệu nội bộ và không được đăng ra ngoài.
    """
    if not form.body_md_path:
        return ""
    p = Path(form.body_md_path)
    if not p.exists():
        return ""
    md = p.read_text(encoding="utf-8")
    # Bỏ khối tiêu đề + ghi nguồn mà renderer đã chèn: trang này đã có phần đó ở
    # trên, để lại thành lặp hai lần.
    dau = md.find("\n> Bản dựng lại")
    if dau >= 0:
        cuoi = md.find("\n\n", dau + 1)
        if cuoi > 0:
            md = md[cuoi:]
    return md.strip()


def render_form_page(session, form: LegalForm,
                     slug_by_num: dict[str, str]) -> str:
    nghiep_vu = json.loads(form.nghiep_vu or "[]")
    tags = ["bieu-mau", form.source] + [f"nv-{m.replace('_', '-')}" for m in nghiep_vu]
    # Cờ hiệu lực thành tag để Quartz lọc được: "cho tôi xem mọi biểu mẫu đã hết
    # hiệu lực" là câu hỏi người vận hành hỏi thật.
    if form.eff_state:
        tags.append(f"hl-{form.eff_state.replace('_', '-')}")
    if form.delisted_at:
        tags.append("da-bi-go")
    khoi_ngay = (f'created: "{form.updated_on}"\nmodified: "{form.updated_on}"\n'
                 if form.updated_on else "")
    return PAGE_TEMPLATE.format(
        short_title=_short(form.title or form.form_key),
        khoi_ngay=khoi_ngay,
        form_key=form.form_key,
        source=form.source,
        nghiep_vu_yaml=_yaml_list(nghiep_vu),
        phan_loai=form.audience or "chua_ro",
        tags=_yaml_list(tags),
        title=form.title or form.form_key,
        hieu_luc=form.eff_state or bm_eff.KHONG_RO,
        khoi_hieu_luc=_khoi_hieu_luc(form),
        khoi_meta=_khoi_meta(form, nghiep_vu),
        ghi_nguon=GHI_NGUON,
        khoi_tai_ve=_khoi_tai_ve(form),
        khoi_can_cu=_khoi_can_cu(session, form, slug_by_num),
        noi_dung=_noi_dung(form) or "*Chưa dựng được nội dung cho biểu mẫu này.*",
        khoi_nguon=_khoi_nguon(form),
    )


def render_muc_luc(session, forms: list[LegalForm]) -> str:
    """Mục lục theo nhóm nghiệp vụ — cửa vào của cả kho biểu mẫu."""
    theo_nhom: dict[str, list[LegalForm]] = {}
    for f in forms:
        for ma in json.loads(f.nghiep_vu or "[]"):
            theo_nhom.setdefault(ma, []).append(f)

    dong = [
        "---",
        'title: "Biểu mẫu cho doanh nghiệp"',
        'tags: ["bieu-mau", "muc-luc"]',
        "---",
        "",
        "# Biểu mẫu cho doanh nghiệp",
        "",
        f"{len(forms)} biểu mẫu, xếp theo nghiệp vụ. Mỗi trang có bản Word điền "
        "được và bản PDF để in.",
        "",
        GHI_NGUON,
        "",
    ]
    for ma, ten in NGHIEP_VU.items():
        nhom = theo_nhom.get(ma)
        if not nhom:
            continue
        dong.append(f"## {ten} ({len(nhom)})")
        dong.append("")
        for f in sorted(nhom, key=lambda x: (x.title or "")):
            dong.append(f"- [[{public_slug_bieu_mau(f)}|{_short(f.title or f.form_key, 90)}]]")
        dong.append("")
    return "\n".join(dong)


def export_forms(session, out_dir: Path,
                 slug_by_num: dict[str, str] | None = None) -> FormPublishStats:
    """Ghi trang cho từng biểu mẫu doanh nghiệp, cộng một trang mục lục.

    Chỉ ghi lại file có nội dung thay đổi — `published_hash` giữ dấu vết bản đã
    đăng, để mỗi lần publish chỉ chạm vào phần thật sự đổi thay vì tạo một commit
    khổng lồ. Cùng cơ chế với export_documents().
    """
    stats = FormPublishStats()
    forms_dir = Path(out_dir) / THU_MUC
    forms_dir.mkdir(parents=True, exist_ok=True)
    slug_by_num = slug_by_num or {}

    slug_hop_le: set[str] = set()
    da_dang: list[LegalForm] = []

    forms = (
        loc_dang_cong_khai(session.query(LegalForm))
        .filter(LegalForm.crawl_status == "OK")
        .order_by(LegalForm.form_key)
        .all()
    )

    for form in forms:
        if not form.body_md_path:
            # Chưa dựng file thì chưa có gì để đăng. Không ghi trang rỗng: một
            # trang trống dưới URL trông như chính thức còn tệ hơn không có trang.
            stats.skipped_no_content += 1
            continue

        slug = public_slug_bieu_mau(form)
        form.public_slug = slug
        slug_hop_le.add(slug)
        da_dang.append(form)

        page = render_form_page(session, form, slug_by_num)
        digest = content_hash(page)
        path = forms_dir / f"{slug}.md"

        if form.published_hash == digest and path.exists():
            stats.unchanged += 1
            continue

        path.write_text(page, encoding="utf-8")
        form.published_hash = digest
        stats.written += 1

    if da_dang:
        muc_luc = render_muc_luc(session, da_dang)
        (forms_dir / "index.md").write_text(muc_luc, encoding="utf-8")
        slug_hop_le.add("index")
        stats.moc_pages = 1

    stats.orphan_removed = remove_orphan_pages(forms_dir, slug_hop_le)
    return stats


def sao_chep_file_tai_ve(session, out_dir: Path) -> int:
    """Chép DOCX/PDF sang thư mục trang công khai để link tải chạy được.

    Chép chứ không link tượng trưng: trang công khai được đẩy sang một repo
    KHÁC, mà link tượng trưng thì không đi qua git sang repo đó.

    RÀNG BUỘC ĐI KÈM: mọi file hàm này chép sang đều phải có một link trỏ tới nó
    trong `_khoi_tai_ve()`. Hai hàm nằm cạnh nhau nhưng độc lập, nên sửa bên kia
    mà quên bên này là file lặng lẽ thành mồ côi — nằm trong repo công khai, tính
    vào dung lượng clone, không trang nào tới được. Đã xảy ra một lần với 653 file
    .docx; test `test_moi_file_chep_sang_deu_co_duong_toi_tu_trang` giữ chốt này.
    """
    import shutil

    forms_dir = Path(out_dir) / THU_MUC
    forms_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for form in loc_dang_cong_khai(session.query(LegalForm)).all():
        for duong_dan in (form.docx_path, form.pdf_path):
            if not duong_dan:
                continue
            src = Path(duong_dan)
            if not src.exists():
                continue
            dich = forms_dir / src.name
            if dich.exists() and dich.stat().st_size == src.stat().st_size:
                continue
            shutil.copy2(src, dich)
            n += 1
    return n


__all__ = [
    "THU_MUC", "GHI_NGUON", "FormPublishStats",
    "public_slug_bieu_mau", "render_form_page", "render_muc_luc",
    "export_forms", "sao_chep_file_tai_ve",
]
