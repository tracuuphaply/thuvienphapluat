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

CHỈ ĐĂNG MẪU `is_business = 1`. Trang này là mục lục cho chủ doanh nghiệp; đăng
cả biểu quyết toán ngân sách của Kho bạc Nhà nước là phá đúng thứ phễu ba tầng
vừa lọc ra.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from src.legal.form_taxonomy import NGHIEP_VU, ten_nhom_hop_dong
from src.publish.site_exporter import content_hash, remove_orphan_pages
from src.sources.tvpl_forms_parse import SOURCE_HOP_DONG
from src.storage.public_slug import slugify_doc_num
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
tags: {tags}
---

# {title}

{khoi_meta}

{ghi_nguon}

## Tải về

{khoi_tai_ve}

## Căn cứ pháp lý

{khoi_can_cu}

## Nội dung biểu mẫu

{noi_dung}

## Nguồn

- Trang gốc trên Thư viện Pháp luật: <{url}>
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
    """Link tải. DOCX đứng trước: biểu mẫu là để ĐIỀN, PDF không điền được."""
    dong = []
    for nhan, duong_dan in (("Bản Word (.docx) — điền được", form.docx_path),
                            ("Bản PDF — để in", form.pdf_path)):
        if duong_dan and Path(duong_dan).exists():
            dong.append(f"- [{nhan}](./{Path(duong_dan).name})")
    if not dong:
        return ("*Chưa dựng được file tải về cho biểu mẫu này. "
                "Nội dung đầy đủ vẫn ở phần dưới.*")
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
        khoi_meta=_khoi_meta(form, nghiep_vu),
        ghi_nguon=GHI_NGUON,
        khoi_tai_ve=_khoi_tai_ve(form),
        khoi_can_cu=_khoi_can_cu(session, form, slug_by_num),
        noi_dung=_noi_dung(form) or "*Chưa dựng được nội dung cho biểu mẫu này.*",
        url=form.url or "",
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
        session.query(LegalForm)
        .filter(LegalForm.is_business.is_(True))
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
    """
    import shutil

    forms_dir = Path(out_dir) / THU_MUC
    forms_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for form in (session.query(LegalForm)
                 .filter(LegalForm.is_business.is_(True)).all()):
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
