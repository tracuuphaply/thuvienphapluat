"""
Tìm biểu mẫu theo từ khoá — FTS5 trong rag.db.

VÌ SAO KHÔNG DÙNG `LIKE '%…%'`. Người dùng gõ "hop dong lao dong" không dấu, gõ
"hoá đơn" trong khi tiêu đề viết "hóa đơn". FTS5 với `remove_diacritics 2` khớp cả
hai; LIKE thì không khớp cái nào. Đây đúng cấu hình mà bảng legal_chunks_fts đang
dùng, giữ nguyên để hai đường tìm kiếm cư xử như nhau.

NHƯNG `remove_diacritics 2` KHÔNG ĐỦ CHO CHỮ Đ. Đ/đ là ký tự RIÊNG (U+0110/U+0111),
không phải chữ cái kèm dấu tổ hợp, nên FTS5 giữ nguyên: "HỢP ĐỒNG" gấp thành
"HOP ĐONG" chứ không phải "HOP DONG". Người gõ "hop dong lao dong" — cách gõ phổ
biến nhất trên điện thoại — không ra kết quả nào. Đây đúng cạm bẫy mà
`src/rag/citation_check.fold_dau()` sinh ra để xử lý, nên dùng lại hàm đó thay vì
viết bản thứ hai rồi để hai bên trôi khác nhau. Cột `khong_dau` giữ bản đã gấp,
và câu hỏi cũng được gấp trước khi đưa vào MATCH.

VÌ SAO ĐẶT TRONG rag.db CHỨ KHÔNG PHẢI legal_docs.db. rag.db là kho truy xuất,
legal_docs.db là kho dữ kiện. Bảng FTS dựng lại được hoàn toàn từ legal_forms nên
nó thuộc về kho truy xuất — mất cũng chỉ cần dựng lại, không mất dữ liệu.

Bảng KHÔNG dùng `content=` (external content) như legal_chunks_fts: bảng nguồn nằm
ở CƠ SỞ DỮ LIỆU KHÁC nên trigger đồng bộ không bắc qua được. Ở đây chép dữ liệu
vào thẳng bảng FTS, và `dung_lai_chi_muc()` dựng lại toàn bộ — 662 mẫu hợp đồng
cộng vài nghìn biểu mẫu là chuyện của vài giây.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.config import DATA_DIR
from src.rag.citation_check import fold_dau
from src.rag.db_rag import RAGDatabase

logger = logging.getLogger(__name__)

RAG_DB_PATH = DATA_DIR / "rag.db"


@dataclass
class KetQuaTim:
    form_key: str
    title: str
    source: str
    nghiep_vu: list[str]
    url: str


def _ket_noi(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or RAG_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def dung_bang(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS forms_fts USING fts5(
            form_key UNINDEXED,
            title,
            keywords,
            khong_dau,
            nghiep_vu UNINDEXED,
            source UNINDEXED,
            url UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    conn.commit()


def dung_lai_chi_muc(session, db_path: Path | None = None) -> int:
    """Dựng lại toàn bộ chỉ mục từ bảng legal_forms. Trả về số mẫu đã nạp.

    CHỈ nạp mẫu `is_business = 1`. Chỉ mục này phục vụ lệnh tra cứu của chủ doanh
    nghiệp; nạp cả mẫu báo cáo ngân sách của Kho bạc vào đây là phá đúng thứ mà
    phễu ba tầng vừa lọc ra.

    CỐ Ý KHÔNG DÙNG `loc_dang_cong_khai()`. Hàm đó gộp doanh nghiệp và cá nhân
    cho TRANG CÔNG KHAI — nơi người đọc tự chọn phần mình cần. Chỉ mục này thì
    chỉ có một bên tiêu thụ là bot Telegram của chủ doanh nghiệp, và ở đó không
    có chỗ nào để chọn: đổ thêm hàng nghìn mẫu cá nhân vào là mỗi lần gõ
    `/bieumau hợp đồng` lại lẫn mẫu ly hôn với mẫu thừa kế. Muốn phục vụ cá nhân
    trên Telegram thì thêm lệnh riêng, không trộn vào đây.
    """
    from src.storage.models import LegalForm

    conn = _ket_noi(db_path)
    try:
        dung_bang(conn)
        conn.execute("DELETE FROM forms_fts")
        rows = (
            session.query(LegalForm)
            .filter(LegalForm.is_business.is_(True))
            .filter(LegalForm.crawl_status == "OK")
            .all()
        )
        conn.executemany(
            "INSERT INTO forms_fts "
            "(form_key, title, keywords, khong_dau, nghiep_vu, source, url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (f.form_key, f.title or "", tu_khoa,
                 fold_dau(f"{f.title or ''} {tu_khoa}"),
                 f.nghiep_vu or "[]", f.source, f.url or "")
                for f, tu_khoa in (
                    (f, " ".join(json.loads(f.keywords or "[]"))) for f in rows
                )
            ],
        )
        conn.commit()
        logger.info("Đã nạp %d biểu mẫu vào chỉ mục tìm kiếm", len(rows))
        return len(rows)
    finally:
        conn.close()


def tim(tu_khoa: str, gioi_han: int = 10,
        db_path: Path | None = None) -> list[KetQuaTim]:
    """Tìm biểu mẫu. Trả về rỗng khi câu hỏi không còn token nào dùng được.

    Dùng lại `RAGDatabase.build_fts_query()` để cùng một cách thoát ký tự với
    phần tìm văn bản: câu "Xây dựng & Bất động sản" từng ném lỗi cú pháp FTS5 rồi
    rơi về nhánh dự phòng và trả 0 kết quả.
    """
    # Gấp dấu TRƯỚC khi dựng biểu thức: "hop dong" và "hợp đồng" phải cùng
    # khớp một cột `khong_dau` đã gấp sẵn.
    bieu_thuc = RAGDatabase.build_fts_query(fold_dau(tu_khoa))
    if not bieu_thuc:
        return []

    conn = _ket_noi(db_path)
    try:
        dung_bang(conn)
        rows = conn.execute(
            "SELECT form_key, title, source, nghiep_vu, url FROM forms_fts "
            "WHERE forms_fts MATCH ? ORDER BY rank LIMIT ?",
            (bieu_thuc, gioi_han),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("Tìm biểu mẫu lỗi (%s) — trả rỗng", e)
        return []
    finally:
        conn.close()

    return [
        KetQuaTim(
            form_key=r["form_key"], title=r["title"], source=r["source"],
            nghiep_vu=json.loads(r["nghiep_vu"] or "[]"), url=r["url"],
        )
        for r in rows
    ]


def dem_theo_nghiep_vu(session) -> dict[str, int]:
    """Số biểu mẫu doanh nghiệp theo từng nhóm nghiệp vụ.

    Một mẫu có hai nhóm thì được đếm ở CẢ HAI: đây là số để người dùng biết bấm
    vào nhóm nào có gì, không phải số để cộng ra tổng kho.
    """
    from src.storage.models import LegalForm

    dem: dict[str, int] = {}
    rows = (
        session.query(LegalForm.nghiep_vu)
        .filter(LegalForm.is_business.is_(True))
        .all()
    )
    for (nv,) in rows:
        for ma in json.loads(nv or "[]"):
            dem[ma] = dem.get(ma, 0) + 1
    return dem


__all__ = ["KetQuaTim", "dung_bang", "dung_lai_chi_muc", "tim", "dem_theo_nghiep_vu"]
