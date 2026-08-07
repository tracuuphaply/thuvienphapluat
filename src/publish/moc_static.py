"""
Trang chỉ mục cho site công khai — bảng Markdown thật, không dùng Dataview.

VÌ SAO KHÔNG DÙNG LẠI MOC CỦA VAULT: `moc_generator.py` dựng toàn bộ MOC và
Dashboard bằng khối ```dataview```. Dataview là plugin của app Obsidian; Quartz
build tĩnh nên KHÔNG thực thi nó — các khối đó sẽ hiện ra như khối mã trần hoặc
biến mất, và trang chỉ mục trở thành trang trống.

Vì vậy bản công khai có bộ chỉ mục riêng, truy vấn thẳng SQLite lúc build.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from src.legal import effectivity
from src.legal.provinces import province_name
from src.obsidian.vsic import BY_CODE, VSIC_LEVEL1
from src.storage.models import Document

logger = logging.getLogger(__name__)

MAX_ROWS_PER_INDEX = 300


def _row(doc: Document) -> str:
    state = effectivity.label(doc.eff_state or effectivity.KHONG_RO)
    return (f"| [[{doc.public_slug}\\|{doc.doc_num}]] | {doc.title or ''} | "
            f"{doc.agency_name or ''} | {doc.issue_date or ''} | {state} |")


HEADER = "| Số hiệu | Tên văn bản | Cơ quan ban hành | Ngày ban hành | Hiệu lực |\n|---|---|---|---|---|"


def _index_page(title: str, intro: str, docs: list[Document]) -> str:
    lines = [f"# {title}", "", intro, ""]
    if not docs:
        lines.append("*Chưa có văn bản nào trong nhóm này.*")
    else:
        lines.append(f"**{len(docs)} văn bản.**")
        if len(docs) > MAX_ROWS_PER_INDEX:
            lines.append(
                f"\n*Chỉ liệt kê {MAX_ROWS_PER_INDEX} văn bản mới nhất. "
                f"Dùng ô tìm kiếm để tra các văn bản còn lại.*"
            )
        lines += ["", HEADER]
        lines += [_row(d) for d in docs[:MAX_ROWS_PER_INDEX]]
    return "\n".join(lines) + "\n"


def export_indexes(session, out_dir: Path, version: str) -> int:
    """Sinh trang chỉ mục theo ngành, cơ quan, địa bàn và năm."""
    written = 0
    docs = (
        session.query(Document)
        .filter(Document.is_vbqppl == True)  # noqa: E712
        .filter(Document.public_slug.isnot(None))
        .order_by(Document.issue_date.desc())
        .all()
    )
    by_key = {d.doc_key: d for d in docs}

    # ── Theo ngành VSIC: lấy ngành đứng đầu của mỗi văn bản ──
    top_industry = session.execute(text("""
        SELECT doc_key, vsic_code FROM (
            SELECT doc_key, vsic_code,
                   ROW_NUMBER() OVER (PARTITION BY doc_key ORDER BY impact_pct_doc DESC) rn
            FROM document_industry_impact WHERE scorer_version = :v
        ) WHERE rn = 1
    """), {"v": version}).mappings().all()

    by_industry: dict[str, list[Document]] = defaultdict(list)
    for row in top_industry:
        doc = by_key.get(row["doc_key"])
        if doc:
            by_industry[row["vsic_code"]].append(doc)

    industry_dir = out_dir / "nganh"
    industry_dir.mkdir(parents=True, exist_ok=True)
    for nganh in VSIC_LEVEL1:
        code = nganh["ma"]
        group = by_industry.get(code, [])
        (industry_dir / f"{code}-{_slug(nganh['ten_ngan'])}.md").write_text(
            _index_page(
                f"Ngành {code} — {nganh['ten_ngan']}",
                f"Văn bản pháp luật có tác động lớn nhất tới ngành **{nganh['ten']}** "
                f"(VSIC cấp 1, mã {code} theo Quyết định 27/2018/QĐ-TTg).",
                group,
            ),
            encoding="utf-8",
        )
        written += 1

    # ── Theo địa bàn ──
    by_province: dict[str, list[Document]] = defaultdict(list)
    for doc in docs:
        if doc.province_code_current:
            by_province[doc.province_code_current].append(doc)

    province_dir = out_dir / "dia-ban"
    province_dir.mkdir(parents=True, exist_ok=True)
    for code, group in sorted(by_province.items()):
        name = province_name(code)
        (province_dir / f"{code}.md").write_text(
            _index_page(
                f"Địa bàn — {name}",
                f"Văn bản do chính quyền **{name}** ban hành. Các văn bản này "
                f"CHỈ áp dụng trong phạm vi địa bàn, không áp dụng toàn quốc.",
                group,
            ),
            encoding="utf-8",
        )
        written += 1

    # ── Theo năm ban hành ──
    by_year: dict[int, list[Document]] = defaultdict(list)
    for doc in docs:
        if doc.issue_date:
            by_year[doc.issue_date.year].append(doc)

    year_dir = out_dir / "nam"
    year_dir.mkdir(parents=True, exist_ok=True)
    for year, group in sorted(by_year.items(), reverse=True):
        (year_dir / f"{year}.md").write_text(
            _index_page(f"Văn bản ban hành năm {year}", "", group), encoding="utf-8"
        )
        written += 1

    (out_dir / "index.md").write_text(
        _home_page(session, docs, by_industry, by_province, by_year), encoding="utf-8"
    )
    written += 1
    return written


def _home_page(session, docs, by_industry, by_province, by_year) -> str:
    state_counts = session.execute(text(
        "SELECT eff_state, COUNT(*) n FROM documents WHERE is_vbqppl = 1 "
        "GROUP BY eff_state ORDER BY n DESC"
    )).mappings().all()

    lines = [
        "# Kho văn bản pháp luật — tra cứu và kiểm chứng",
        "",
        "Trang này công bố **dữ kiện** của các văn bản quy phạm pháp luật được dùng",
        "làm căn cứ trong các báo cáo pháp lý: số hiệu, cơ quan ban hành, cấp hiệu",
        "lực, tình trạng hiệu lực, phạm vi áp dụng và đồ thị dẫn chiếu giữa chúng.",
        "",
        "Mục đích là để người đọc báo cáo kiểm chứng được mọi số hiệu được trích dẫn.",
        "",
        "> **Bản sao không chính thức.** Trang này không đăng toàn văn. Bản có giá trị",
        "> pháp lý là bản công bố trên hệ thống của cơ quan nhà nước; mỗi trang văn bản",
        "> đều có link về nguồn gốc.",
        "",
        "## Kho hiện có",
        "",
        f"- **{len(docs)}** văn bản quy phạm pháp luật",
        f"- **{len(by_province)}** địa bàn cấp tỉnh",
        f"- Năm ban hành: {min(by_year)}–{max(by_year)}" if by_year else "",
        "",
        "| Tình trạng hiệu lực | Số văn bản |",
        "|---|---:|",
    ]
    for row in state_counts:
        lines.append(f"| {effectivity.label(row['eff_state'] or '')} | {row['n']} |")

    lines += ["", "## Tra theo ngành nghề (VSIC cấp 1)", ""]
    for nganh in VSIC_LEVEL1:
        code = nganh["ma"]
        n = len(by_industry.get(code, []))
        lines.append(
            f"- [[nganh/{code}-{_slug(nganh['ten_ngan'])}\\|{code} — {nganh['ten_ngan']}]] ({n})"
        )

    lines += ["", "## Tra theo địa bàn", ""]
    for code in sorted(by_province):
        lines.append(f"- [[dia-ban/{code}\\|{province_name(code)}]] ({len(by_province[code])})")

    lines += ["", "## Tra theo năm ban hành", ""]
    for year in sorted(by_year, reverse=True):
        lines.append(f"- [[nam/{year}\\|{year}]] ({len(by_year[year])})")

    lines += [
        "",
        "## Về điểm tác động ngành",
        "",
        "Mỗi trang văn bản có bảng mức độ tác động tới 21 ngành VSIC. Chỉ số này đo",
        "**cường độ quy phạm** hướng vào một ngành — số lượng và mức độ cưỡng chế của",
        "các mệnh đề ràng buộc, nhân với mức liên quan tới ngành, có tính trọng số theo",
        "cấp hiệu lực pháp lý. Nó **không** đo chi phí kinh tế.",
        "",
        "Phương pháp phỏng theo RegData của QuantGov (Mercatus Center), thay bộ phân",
        "loại ngành NAICS bằng hệ thống ngành kinh tế Việt Nam.",
    ]
    return "\n".join(l for l in lines if l is not None) + "\n"


def _slug(name: str) -> str:
    import re
    import unicodedata

    text_ = name.translate(str.maketrans({"Đ": "D", "đ": "d"}))
    text_ = unicodedata.normalize("NFKD", text_)
    text_ = "".join(c for c in text_ if not unicodedata.combining(c))
    return re.sub(r"[^a-zA-Z0-9]+", "-", text_).strip("-").lower()
