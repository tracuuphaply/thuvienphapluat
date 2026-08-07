"""
Sinh nội dung cho trang tra cứu công khai.

MỤC ĐÍCH: người đọc báo cáo pháp lý bấm vào một số hiệu và thấy ngay văn bản đó
có thật, do ai ban hành, còn hiệu lực không, và nó nối với những văn bản nào.
Đó là thứ biến báo cáo từ "một tài liệu" thành "một tài liệu kiểm chứng được".

KHÔNG ĐĂNG TOÀN VĂN. Ba lý do, theo thứ tự quan trọng:

  1. Không cần. Mục đích là kiểm chứng, và metadata + đồ thị dẫn chiếu đã đủ để
     kiểm chứng; ai cần toàn văn thì bấm link về nguồn chính thức.
  2. Dung lượng. Toàn văn là 140 MB HTML và sẽ tăng theo bao đóng dẫn chiếu;
     thời gian build Quartz tăng siêu tuyến tính vì phải tính backlink.
  3. Bản quyền. Điều 15 Luật Sở hữu trí tuệ nói rõ văn bản quy phạm pháp luật
     KHÔNG thuộc đối tượng bảo hộ quyền tác giả, nên đăng lại là hợp pháp — cái
     không tự do là phần giá trị gia tăng của bên biên tập (bản dịch, tóm tắt,
     lược đồ, cách trình bày). Không đăng toàn văn thì câu hỏi đó không đặt ra.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.legal import effectivity
from src.legal.hierarchy import LEVEL_NON_NORMATIVE, classify
from src.legal.provinces import province_name
from src.obsidian.config_obsidian import HIERARCHY_LABELS
from src.obsidian.vsic import BY_CODE
from src.storage.models import Document, DocumentReference

logger = logging.getLogger(__name__)

# Số hiệu không parse được đều rơi về đây; nó là thùng rác, không phải văn bản.
# Publish nó sẽ tạo một nút khổng lồ vô nghĩa giữa sơ đồ tư duy.
JUNK_TARGETS = frozenset({"Không số", "Khong so", "", "-"})

DISCLAIMER = """> **Bản sao không chính thức.** Trang này là bản trích dữ kiện phục vụ tra cứu
> và kiểm chứng nguồn của các báo cáo pháp lý. Bản có giá trị pháp lý là bản
> công bố trên hệ thống của cơ quan nhà nước — xem mục *Nguồn gốc* bên dưới.
> Trang này không đăng toàn văn và không phải một dịch vụ cơ sở dữ liệu pháp luật."""

PAGE_TEMPLATE = """---
title: "{doc_num} — {short_title}"
doc_num: "{doc_num}"
doc_type: "{doc_type}"
hierarchy_level: {hierarchy_level}
is_vbqppl: {is_vbqppl}
agency: "{agency}"
issue_date: "{issue_date}"
eff_from: "{eff_from}"
eff_state: "{eff_state}"
territorial_scope: "{territorial_scope}"
province: "{province}"
tags: {tags}
---

# {title}

{disclaimer}

## Dữ kiện

| | |
|---|---|
| **Số hiệu** | {doc_num} |
| **Loại văn bản** | {doc_type} |
| **Cấp hiệu lực pháp lý** | {hierarchy_label} |
| **Cơ quan ban hành** | {agency} |
| **Phạm vi áp dụng** | {scope_label} |
| **Ngày ban hành** | {issue_date} |
| **Ngày có hiệu lực** | {eff_from} |
| **Tình trạng hiệu lực** | {eff_state_label} *(tính đến {eff_state_as_of})* |

## Mức độ tác động theo ngành

{impact_table}

## Văn bản liên quan

{references_md}

## Nguồn gốc

{sources_md}
"""

IMPACT_NOTE = """*Chỉ số này đo **cường độ quy phạm** hướng vào một ngành — số lượng và mức độ
cưỡng chế của các mệnh đề ràng buộc, nhân với mức liên quan tới ngành. Nó
**không** đo chi phí kinh tế. Cách tính: xem `src/analysis/`.*

| Ngành (VSIC cấp 1) | Tỷ trọng tác động | Cường độ |
|---|---:|---:|
"""


@dataclass
class PublishStats:
    written: int = 0
    unchanged: int = 0
    skipped_junk: int = 0
    mocs: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def content_hash(text_content: str) -> str:
    return hashlib.sha256(text_content.encode("utf-8")).hexdigest()


def _short(title: str, limit: int = 70) -> str:
    title = (title or "").replace('"', "'").strip()
    return title if len(title) <= limit else title[: limit - 1] + "…"


def _yaml_list(items: list[str]) -> str:
    return "[" + ", ".join(f'"{i}"' for i in items) + "]" if items else "[]"


def _impact_table(rows: list[dict]) -> str:
    if not rows:
        return ("*Chưa chấm điểm tác động cho văn bản này — có thể vì nó không "
                "chứa mệnh đề ràng buộc nào (thông báo, công điện), hoặc chưa "
                "được đưa vào chỉ mục.*")
    body = "\n".join(
        f"| {BY_CODE.get(r['vsic_code'], {}).get('ten_ngan', r['vsic_code'])} "
        f"({r['vsic_code']}) | {r['impact_pct_doc']:.1f}% | {r['impact_pct_industry']:.0f} |"
        for r in rows
    )
    return IMPACT_NOTE + body


def _sources(doc: Document) -> str:
    lines = []
    if doc.moj_url:
        lines.append(f"- Bản ghi gốc trên hệ thống Bộ Tư pháp: <{doc.moj_url}>")
    if doc.tvpl_url:
        lines.append(f"- Trang Thư viện Pháp luật: <{doc.tvpl_url}>")
    if not lines:
        lines.append("- *Chưa ghi nhận được địa chỉ nguồn cho văn bản này.*")
    return "\n".join(lines)


def _references(session, doc: Document, slug_by_num: dict[str, str]) -> str:
    """Wikilink hai chiều — đây là thứ tạo ra sơ đồ tư duy trên trang công khai."""
    out: list[str] = []

    outgoing = session.query(DocumentReference).filter(
        DocumentReference.source_doc_id == doc.id
    ).all()
    if outgoing:
        out.append("**Văn bản này dẫn chiếu tới:**\n")
        for ref in outgoing:
            target = (ref.target_doc_num or "").strip()
            if target in JUNK_TARGETS:
                continue
            slug = slug_by_num.get(target)
            link = f"[[{slug}|{target}]]" if slug else f"`{target}` *(chưa có trong kho)*"
            out.append(f"- {ref.relation_type}: {link}")

    incoming = session.query(DocumentReference).filter(
        DocumentReference.target_doc_num == doc.doc_num
    ).all()
    if incoming:
        out.append("\n**Bị các văn bản sau tác động:**\n")
        for ref in incoming:
            src = session.query(Document).filter(
                Document.id == ref.source_doc_id
            ).first()
            if not src:
                continue
            slug = slug_by_num.get(src.doc_num)
            link = f"[[{slug}|{src.doc_num}]]" if slug else f"`{src.doc_num}`"
            out.append(f"- {ref.relation_type} bởi {link}")

    return "\n".join(out) if out else "*Chưa ghi nhận văn bản liên quan.*"


def build_slug_index(session) -> dict[str, str]:
    """Số hiệu → slug, chỉ nhận số hiệu duy nhất trong kho.

    Số hiệu xuất hiện ở nhiều tỉnh thì bản thân dẫn chiếu đã mơ hồ — không có
    căn cứ để chọn tỉnh nào, nên để link chưa phân giải còn hơn trỏ nhầm sang
    văn bản của địa phương khác.
    """
    counts: dict[str, int] = {}
    slugs: dict[str, str] = {}
    for doc_num, slug in session.query(Document.doc_num, Document.public_slug).all():
        counts[doc_num] = counts.get(doc_num, 0) + 1
        if slug:
            slugs[doc_num] = slug
    return {n: s for n, s in slugs.items() if counts[n] == 1}


def render_page(session, doc: Document, impacts: list[dict],
                slug_by_num: dict[str, str]) -> str:
    level = LEVEL_NON_NORMATIVE if doc.hierarchy_level is None else int(doc.hierarchy_level)
    state = doc.eff_state or effectivity.KHONG_RO
    scope = doc.territorial_scope or "khong_xac_dinh"
    province = province_name(doc.province_code_current)

    if scope == "tinh":
        scope_label = f"Địa phương — {province}" if province else "Địa phương (chưa rõ tỉnh)"
    elif scope == "trung_uong":
        scope_label = "Toàn quốc"
    else:
        scope_label = "Chưa xác định"

    # Cơ quan ban hành: dùng suy diễn từ số hiệu khi kho chưa có.
    # Bảng thứ bậc đã biết "/NQ-CP" là Chính phủ (nên mới xếp được cấp 5), nên
    # hiện "Chưa xác định" là bỏ phí một dữ kiện chắc chắn đúng — quy tắc pháp
    # lý chứ không phải phỏng đoán.
    agency = doc.agency_name
    if not agency:
        agency = classify(doc.doc_num or "", doc.doc_type or "", "").agency
    agency = agency or "Chưa xác định"

    tags = ["van-ban"]
    if doc.doc_type_norm:
        tags.append(doc.doc_type_norm.replace("_", "-"))
    if state:
        tags.append(state.replace("_", "-"))

    return PAGE_TEMPLATE.format(
        doc_num=doc.doc_num,
        short_title=_short(doc.title),
        title=doc.title or doc.doc_num,
        doc_type=doc.doc_type or "",
        hierarchy_level=level,
        hierarchy_label=HIERARCHY_LABELS.get(level, HIERARCHY_LABELS[LEVEL_NON_NORMATIVE]),
        is_vbqppl=str(bool(doc.is_vbqppl)).lower(),
        agency=agency,
        issue_date=doc.issue_date or "",
        eff_from=doc.eff_from or "",
        eff_state=state,
        eff_state_label=effectivity.label(state),
        eff_state_as_of=doc.eff_state_as_of or "",
        territorial_scope=scope,
        province=province,
        scope_label=scope_label,
        tags=_yaml_list(tags),
        disclaimer=DISCLAIMER,
        impact_table=_impact_table(impacts),
        references_md=_references(session, doc, slug_by_num),
        sources_md=_sources(doc),
    )


def impacts_by_doc(session, version: str) -> dict[str, list[dict]]:
    """Điểm tác động của mọi văn bản, gom theo doc_key.

    Gom theo doc_key chứ không theo số hiệu: hai văn bản khác tỉnh trùng số hiệu
    sẽ trộn thành một bảng có ngành lặp lại.
    """
    rows = session.execute(text("""
        SELECT doc_key, vsic_code, impact_pct_doc, impact_pct_industry
        FROM document_industry_impact
        WHERE scorer_version = :v AND impact_pct_doc >= 1.0
        ORDER BY doc_key, impact_pct_doc DESC
    """), {"v": version}).mappings().all()

    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["doc_key"], []).append(dict(r))
    return out


def export_documents(session, out_dir: Path, version: str,
                     only_vbqppl: bool = True) -> PublishStats:
    """Ghi trang cho từng văn bản. Chỉ ghi lại file có nội dung thay đổi.

    `published_hash` giữ dấu vết bản đã đẩy lên trang công khai, để mỗi lần
    publish chỉ chạm vào phần thật sự đổi thay vì tạo một commit khổng lồ.
    """
    stats = PublishStats()
    docs_dir = out_dir / "van-ban"
    docs_dir.mkdir(parents=True, exist_ok=True)

    slug_by_num = build_slug_index(session)
    impacts = impacts_by_doc(session, version)

    query = session.query(Document)
    if only_vbqppl:
        # Văn bản không phải QPPL vẫn nằm trong kho làm ngữ cảnh, nhưng đưa lên
        # trang tra cứu sẽ khiến người đọc tưởng chúng là căn cứ pháp lý.
        query = query.filter(Document.is_vbqppl == True)  # noqa: E712

    for doc in query.order_by(Document.id).all():
        if (doc.doc_num or "").strip() in JUNK_TARGETS or not doc.public_slug:
            stats.skipped_junk += 1
            continue

        page = render_page(session, doc, impacts.get(doc.doc_key, []), slug_by_num)
        digest = content_hash(page)
        path = docs_dir / f"{doc.public_slug}.md"

        if doc.published_hash == digest and path.exists():
            stats.unchanged += 1
            continue

        path.write_text(page, encoding="utf-8")
        doc.published_hash = digest
        stats.written += 1

    return stats
