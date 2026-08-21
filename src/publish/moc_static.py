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
from src.publish import site_exporter
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


def export_indexes(session, out_dir: Path, version: str,
                   trang_tong_quan: str | None = None) -> int:
    """Sinh trang chỉ mục theo ngành, cơ quan, địa bàn và năm.

    `trang_tong_quan` — tên file cho trang tổng quan (thống kê kho, mục lục
    ngành/địa bàn/năm, ghi chú cách tính điểm tác động). MẶC ĐỊNH KHÔNG SINH.

    Trước đây nó luôn được ghi ra `index.md`, tức trang chủ. Nay trang chủ là
    ứng dụng tra cứu ở `tro-ly/`, chép thẳng vào gốc bản dựng — xem bước "Chép
    trang trợ lý" trong `.github/workflows/build.yml` của repo công khai. Vẫn
    sinh `index.md` thì Quartz phát ra `public/index.html` rồi bị bản chép đè
    lên: dựng một file chỉ để bị ghi đè, và là chỗ để hai bên lệch nhau về sau.

    Tham số vẫn còn chứ không xoá hẳn, vì trang tổng quan là lối vào duy nhất
    tới 21 trang ngành, 31 trang địa bàn và 33 trang năm. Muốn có lại thì
    truyền tên khác, ví dụ `"tong-quan.md"` — nó sẽ nằm ở /tong-quan chứ không
    chiếm trang chủ nữa.
    """
    written = 0
    # Chỉ mục liệt kê văn bản NGHIỆP VỤ. Văn bản kéo về theo dẫn chiếu vẫn có
    # trang riêng và vẫn tới được bằng wikilink từ văn bản dẫn tới nó — đó đúng
    # là công dụng của chúng: kiểm chứng căn cứ. Nhưng đưa vào chỉ mục thì
    # chúng chôn mất phần cần đọc: 3.255/4.200 mục là văn bản nền, trong đó
    # 2.134 đã hết hiệu lực toàn bộ.
    docs = (
        session.query(Document)
        .filter(Document.is_vbqppl == True)  # noqa: E712
        .filter(Document.public_slug.isnot(None))
        .filter((Document.is_closure_node.is_(None))
                | (Document.is_closure_node == False))  # noqa: E712
        .order_by(Document.issue_date.desc())
        .all()
    )
    # Bỏ số hiệu rác đúng như bên sinh trang. Bộ sinh trang bỏ chúng, chỉ mục
    # thì không, nên trang chủ đếm dư một so với số trang thật sự tồn tại — và
    # mục đó dẫn tới 404. "Không số" là chỗ dồn của mọi số hiệu không parse
    # được, không phải một văn bản.
    docs = [d for d in docs
            if (d.doc_num or "").strip() not in site_exporter.JUNK_TARGETS]
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

    if trang_tong_quan:
        (out_dir / trang_tong_quan).write_text(
            _home_page(session, docs, by_industry, by_province, by_year),
            encoding="utf-8",
        )
        written += 1
    return written


def _home_page(session, docs, by_industry, by_province, by_year) -> str:
    # Đếm NGAY TRÊN `docs` chứ không truy vấn lại. Bản trước hỏi SQL toàn bộ
    # `is_vbqppl = 1` trong khi dòng ngay trên đó đếm `docs` — tức trang chủ ghi
    # "946 văn bản" rồi bày một bảng cộng lại ra 4.201. Hai tập khác nhau trình
    # bày như một, và người đọc không có cách nào biết. Dùng chung một tập là
    # cách duy nhất khiến chúng không lệch được nữa.
    dem: dict[str, int] = defaultdict(int)
    for d in docs:
        dem[d.eff_state or ""] += 1
    state_counts = [{"eff_state": k, "n": v}
                    for k, v in sorted(dem.items(), key=lambda kv: -kv[1])]

    # Văn bản nền có trang riêng (để link dẫn chiếu không gãy) nhưng cố tình
    # không nằm trong danh mục. Không nói ra thì tổng số trang trên trang web
    # không khớp con số ở đây.
    so_nen = session.execute(text(
        "SELECT COUNT(*) FROM documents WHERE is_vbqppl = 1 "
        "AND public_slug IS NOT NULL AND is_closure_node = 1"
    )).scalar() or 0

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
        f"- **{len(docs)}** văn bản trong danh mục tra cứu",
        f"- **{so_nen}** văn bản nền — vào kho vì bị dẫn chiếu tới, có trang "
        f"riêng nhưng không liệt kê ở các danh mục dưới đây",
        f"- **{len(by_province)}** địa bàn cấp tỉnh",
        f"- Năm ban hành: {min(by_year)}–{max(by_year)}" if by_year else "",
        "",
        f"Tình trạng hiệu lực của {len(docs)} văn bản trong danh mục:",
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
