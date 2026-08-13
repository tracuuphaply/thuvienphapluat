"""
Database connection & CRUD operations.

Supports both SQLite (dev) and PostgreSQL (production) via DATABASE_URL.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Generator

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.config import CLOSURE_SEED_FLOOR, CRAWL_OVERLAP_DAYS, DATABASE_URL
from src.legal import effectivity
from src.legal.field_mapper import phan_loai
from src.legal.hierarchy import classify, resolve_province
from src.storage.migrations import run_migrations
from src.storage.public_slug import make_public_slug
from src.storage.models import (
    Base,
    CrawlRun,
    Document,
    DocumentReference,
    DocumentStatusHistory,
    MojIdIndex,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Engine & Session Factory
# ──────────────────────────────────────────────
_db_url = DATABASE_URL
# For SQLite, strip the async driver prefix for synchronous usage
if "aiosqlite" in _db_url:
    _db_url = _db_url.replace("sqlite+aiosqlite", "sqlite")

engine = create_engine(_db_url, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Tạo bảng nếu chưa có và áp các migration chưa chạy.

    Danh sách ALTER TABLE trước đây nằm thẳng trong hàm này và chạy lại mỗi lần
    khởi động; nay nằm ở src/storage/migrations.py và mỗi bước chỉ chạy một lần,
    có ghi vào bảng schema_migrations.
    """
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        run_migrations(conn)
        _ensure_doc_key(conn)

    logger.info("Database tables initialized.")


def _ensure_doc_key(conn) -> None:
    """Điền doc_key cho bản ghi cũ và dựng chỉ mục duy nhất.

    Kho cũ dùng UNIQUE(doc_num) — ràng buộc đó phải được gỡ bằng
    scripts/migrate_doc_key.py (SQLite không DROP CONSTRAINT được). Hàm này chỉ
    lo phần có thể làm tại chỗ để pipeline không gãy khi cột vừa được thêm.
    """
    from sqlalchemy import text

    rows = conn.execute(text(
        "SELECT id, doc_num, agency_name FROM documents WHERE doc_key IS NULL OR doc_key = ''"
    )).fetchall()
    if rows:
        for row in rows:
            conn.execute(
                text("UPDATE documents SET doc_key = :k WHERE id = :i"),
                {"k": make_doc_key(row[1], row[2]), "i": row[0]},
            )
        conn.commit()
        logger.info("Đã điền doc_key cho %d văn bản", len(rows))

    try:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_doc_key ON documents(doc_key)"
        ))
        conn.commit()
    except Exception as e:
        logger.error("Không tạo được chỉ mục doc_key (có thể còn khoá trùng): %s", e)

    table_sql = conn.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'"
    )).scalar() or ""
    if "UNIQUE (doc_num)" in table_sql.replace("\n", " "):
        logger.warning(
            "documents vẫn còn UNIQUE(doc_num) — văn bản cấp tỉnh trùng số hiệu sẽ "
            "bị nuốt. Chạy: python -m scripts.migrate_doc_key"
        )



@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional session scope."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ──────────────────────────────────────────────
# Document CRUD
# ──────────────────────────────────────────────
def _norm(value: str | None) -> str:
    """Chuẩn hoá để so khớp: bỏ khoảng trắng thừa, thường hoá."""
    return " ".join((value or "").split()).lower()


def make_doc_key(doc_num: str, agency_name: str | None) -> str:
    """Định danh thật của một văn bản.

    Số hiệu chỉ duy nhất trong phạm vi cơ quan ban hành: "67/2026/QĐ-UBND" của
    Hải Phòng và của Đắk Lắk là hai văn bản khác nhau. Khi chưa biết cơ quan thì
    tạm dùng riêng số hiệu — bản ghi sẽ được gộp lại khi cơ quan lộ diện.
    """
    return f"{_norm(doc_num)}::{_norm(agency_name)}"


def get_documents_by_doc_num(session: Session, doc_num: str) -> list[Document]:
    """Mọi văn bản mang cùng số hiệu (nhiều tỉnh có thể trùng số)."""
    return list(session.execute(
        select(Document).where(Document.doc_num == doc_num)
    ).scalars())


def get_document_by_doc_num(session: Session, doc_num: str) -> Document | None:
    """Văn bản duy nhất mang số hiệu này, hoặc None nếu không có / nhập nhằng.

    Trả None khi có nhiều bản trùng số hiệu: không thể chọn bừa một tỉnh.
    Dùng get_documents_by_doc_num khi cần xử lý cả nhóm.
    """
    matches = get_documents_by_doc_num(session, doc_num)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.debug(
            "Số hiệu %s có %d bản của các cơ quan khác nhau — không thể chọn duy nhất",
            doc_num, len(matches),
        )
    return None


def get_document_by_doc_key(session: Session, doc_key: str) -> Document | None:
    stmt = select(Document).where(Document.doc_key == doc_key)
    return session.execute(stmt).scalar_one_or_none()


def resolve_existing_document(session: Session, data: dict) -> Document | None:
    """Tìm bản ghi đã có tương ứng với dữ liệu đang nạp.

    Ưu tiên id của nguồn (chắc chắn nhất), rồi tới định danh số hiệu + cơ quan.
    Chỉ khi cả hai bên đều chưa biết cơ quan mới lùi về so khớp bằng số hiệu,
    và chỉ chấp nhận khi có đúng một ứng viên.
    """
    if data.get("moj_id"):
        found = get_document_by_moj_id(session, data["moj_id"])
        if found:
            return found
    if data.get("tvpl_id"):
        found = get_document_by_tvpl_id(session, data["tvpl_id"])
        if found:
            return found

    doc_num = data.get("doc_num", "")
    agency = data.get("agency_name")
    found = get_document_by_doc_key(session, make_doc_key(doc_num, agency))
    if found:
        return found

    if not _norm(agency):
        # Chưa biết cơ quan: gộp vào bản duy nhất cùng số hiệu nếu không nhập nhằng.
        return get_document_by_doc_num(session, doc_num)

    # Đã biết cơ quan nhưng chưa có doc_key khớp — có thể bản cũ được tạo lúc
    # chưa rõ cơ quan. Nhận lại nếu chỉ có đúng một ứng viên chưa gắn cơ quan.
    candidates = [
        d for d in get_documents_by_doc_num(session, doc_num) if not _norm(d.agency_name)
    ]
    return candidates[0] if len(candidates) == 1 else None


def get_document_by_moj_id(session: Session, moj_id: str) -> Document | None:
    """Find a document by its MOJ internal ID.

    `.first()` chứ không `.scalar_one_or_none()`: moj_id chỉ được đánh chỉ mục,
    KHÔNG duy nhất (một nút bao đóng và một bản nghiệp vụ có thể mang cùng id qua
    hai luồng khác nhau). scalar_one_or_none ném MultipleResultsFound khi trùng,
    làm sập chính bước upsert đang cố gộp chúng.
    """
    stmt = select(Document).where(Document.moj_id == moj_id).order_by(Document.id)
    return session.execute(stmt).scalars().first()


def get_document_by_tvpl_id(session: Session, tvpl_id: str) -> Document | None:
    """Find a document by its TVPL ID (last slug number). Xem get_document_by_moj_id."""
    stmt = select(Document).where(Document.tvpl_id == tvpl_id).order_by(Document.id)
    return session.execute(stmt).scalars().first()


# Vòng đời hiệu lực của văn bản QPPL thay đổi theo thời gian: văn bản hôm nay
# "Còn hiệu lực" ngày mai có thể bị bãi bỏ. Những trường này phải được làm mới
# mỗi lần nguồn trả về giá trị mới, nếu không trạng thái sẽ đóng băng vĩnh viễn
# ở lần cào đầu tiên và hệ thống không bao giờ phát hiện được văn bản hết hiệu lực.
REFRESHABLE_FIELDS = frozenset({
    "eff_status",
    "eff_to",
    "eff_from",
    "issue_date",
    "pub_date",
    "doc_type",
    "agency_name",
    "title",
    "signer",
    "field_name",
    "field_code",
    # Suy trực tiếp từ moj_id nên phải đi theo nó; để ở nhánh "chỉ điền khi
    # rỗng" thì 1015 bản ghi cũ đang rỗng sẽ chỉ được vá nếu tình cờ crawl lại.
    "moj_url",
})


def upsert_document(session: Session, data: dict) -> tuple[Document, bool]:
    """
    Insert or update a document by doc_num.
    Returns (document, is_new).

    Trường trong REFRESHABLE_FIELDS luôn được ghi đè bằng giá trị mới từ nguồn;
    các trường còn lại chỉ điền khi đang rỗng (tránh nguồn yếu ghi đè nguồn mạnh).
    Mọi thay đổi eff_status đều được ghi vào document_status_history.
    """
    doc_num = data.get("doc_num", "")
    existing = resolve_existing_document(session, data)

    if existing:
        old_status = existing.eff_status
        for key, value in data.items():
            if value is None:
                continue
            current = getattr(existing, key, None)
            if current is None or current == "" or current is False:
                setattr(existing, key, value)
            elif key in ("source_tvpl", "source_moj") and value is True:
                setattr(existing, key, value)
            elif key in REFRESHABLE_FIELDS and value != current:
                setattr(existing, key, value)

        # Cơ quan ban hành có thể vừa lộ diện ở lần cào này — định danh phải
        # được tính lại, nếu không bản ghi vẫn mang khoá tạm thời thiếu cơ quan.
        # NHƯNG nếu khoá mới đã thuộc một bản ghi KHÁC (UNIQUE doc_key), đổi sang
        # sẽ ném IntegrityError lúc commit và mất trắng lần enrich này. Trường hợp
        # đó giữ khoá cũ — để một lỗi khoá làm hỏng cả lần cào là tệ hơn nhiều.
        new_key = make_doc_key(existing.doc_num, existing.agency_name)
        if new_key != existing.doc_key:
            clash = session.query(Document).filter(
                Document.doc_key == new_key, Document.id != existing.id
            ).first()
            if clash is None:
                existing.doc_key = new_key
            else:
                logger.warning(
                    "Giữ doc_key cũ %s: khoá mới %s đã thuộc bản #%s",
                    existing.doc_key, new_key, clash.id)

        new_status = existing.eff_status
        if old_status != new_status:
            session.add(
                DocumentStatusHistory(
                    document_id=existing.id,
                    old_status=old_status,
                    new_status=new_status,
                    detected_by="MOJ" if data.get("source_moj") else "TVPL",
                )
            )

        apply_derived_facts(existing)
        existing.updated_at = datetime.now(timezone.utc)
        return existing, False
    else:
        payload = dict(data)
        payload["doc_key"] = make_doc_key(doc_num, payload.get("agency_name"))
        doc = Document(**payload)
        apply_derived_facts(doc)
        session.add(doc)
        session.flush()  # Get the auto-generated ID
        return doc, True


def apply_derived_facts(doc: Document, as_of: date | None = None) -> None:
    """Tính lại thứ bậc, địa bàn, cờ hiệu lực và slug công khai cho một văn bản.

    Gọi ở MỌI đường ghi chứ không chỉ trong script backfill: nếu chỉ backfill
    một lần, mọi văn bản cào về sau đó sẽ có các cột này rỗng và lặng lẽ rơi ra
    khỏi mọi bộ lọc theo cấp, theo địa bàn hay theo hiệu lực.

    Tính lại cả khi cập nhật vì các trường nguồn đều nằm trong REFRESHABLE_FIELDS
    — `eff_status` đổi mà `eff_state` giữ nguyên thì hai cột nói ngược nhau.
    """
    facts = classify(doc.doc_num or "", doc.doc_type or "", doc.agency_name or "")
    doc.hierarchy_level = facts.hierarchy_level
    doc.doc_type_norm = facts.doc_type_norm
    doc.is_vbqppl = facts.is_vbqppl
    doc.territorial_scope = facts.territorial_scope

    # Lĩnh vực TVPL — cùng lý do như cả hàm này: bỏ ở đây thì văn bản cào MỚI có
    # tvpl_field_code rỗng và lặng lẽ rơi khỏi bộ lọc "liên quan doanh nghiệp"
    # của báo cáo (b) — không bao giờ có báo cáo tự động nào ra. Trước đây cột
    # này chỉ được điền bằng scripts/backfill_tvpl_field.py chạy tay. Dùng đúng
    # phan_loai như script đó nên phân loại nhất quán ở mọi đường ghi.
    linh_vuc = phan_loai(doc.field_code, doc.field_name, doc.title)
    doc.tvpl_field_code = linh_vuc.ma
    doc.tvpl_field_source = linh_vuc.nguon

    raw_code, current = resolve_province(doc.agency_name or "")
    doc.province_code_raw = raw_code
    doc.province_code_current = current

    eff = effectivity.resolve(
        doc.eff_status, doc.eff_from, doc.eff_to, as_of or date.today()
    )
    doc.eff_state = eff.state
    doc.eff_state_as_of = eff.as_of
    doc.eff_state_source = eff.source

    if not doc.public_slug:
        doc.public_slug = make_public_slug(doc.doc_num or "", doc.doc_key or "")
    if doc.is_closure_node is None:
        doc.is_closure_node = False


def enqueue_upload(
    session: Session,
    doc: Document,
    provider: str,
    file_kinds: list[str],
    error: str,
) -> None:
    """Xếp một văn bản vào hàng đợi upload để thử lại lần chạy sau.

    Không có bước này thì upload hỏng chỉ để lại một dòng log: văn bản không bao
    giờ được thử lại và cũng không ai biết nó thiếu trên mây. Mỗi văn bản chỉ
    giữ một mục cho mỗi đích lưu trữ — lần hỏng sau cập nhật mục cũ.
    """
    from sqlalchemy import text as _text

    session.execute(_text("""
        INSERT INTO upload_queue (doc_key, doc_num, provider, file_kinds, status,
                                  attempts, last_error, updated_at)
        VALUES (:k, :n, :p, :f, 'PENDING', 1, :e, datetime('now'))
        ON CONFLICT(doc_key, provider) DO UPDATE SET
            file_kinds = excluded.file_kinds,
            status     = 'PENDING',
            attempts   = upload_queue.attempts + 1,
            last_error = excluded.last_error,
            updated_at = datetime('now')
    """), {
        "k": doc.doc_key, "n": doc.doc_num, "p": provider,
        "f": ",".join(file_kinds), "e": (error or "")[:500],
    })


def clear_upload_queue(session: Session, doc_key: str, provider: str) -> None:
    """Xoá mục chờ sau khi văn bản đã lên mây đủ."""
    from sqlalchemy import text as _text

    session.execute(
        _text("DELETE FROM upload_queue WHERE doc_key = :k AND provider = :p"),
        {"k": doc_key, "p": provider},
    )


def pending_uploads(session: Session, limit: int = 100) -> list[dict]:
    """Các văn bản đang chờ đẩy lên mây, cũ nhất trước."""
    from sqlalchemy import text as _text

    rows = session.execute(_text("""
        SELECT doc_key, doc_num, provider, file_kinds, attempts, last_error
        FROM upload_queue WHERE status = 'PENDING'
        ORDER BY updated_at LIMIT :n
    """), {"n": limit}).mappings().all()
    return [dict(r) for r in rows]


def get_crawl_cutoff(session: Session, source: str = "moj") -> tuple[date, str]:
    """Ngày cần quét lùi tới, và lý do chọn ngày đó.

    Thay cửa sổ trượt `today - 30 ngày`: cửa sổ trượt quét lại toàn bộ 30 ngày ở
    mỗi lần chạy (6.906 văn bản để tìm 50 bản mới), và máy tắt lâu hơn 30 ngày là
    mất hẳn phần ở giữa mà không ai biết.

    Vẫn quét lùi quá watermark một quãng OVERLAP_DAYS: /doc/all sắp theo
    issueDate, nhưng văn bản được ĐĂNG lên hệ thống muộn hơn ngày ban hành khá
    nhiều. Cắt đúng watermark sẽ bỏ sót vĩnh viễn mọi văn bản đăng chậm.
    """
    from sqlalchemy import text as _text

    row = session.execute(_text(
        "SELECT high_water_issue_date, low_water_issue_date, overlap_days "
        "FROM crawl_watermark WHERE source = :s"
    ), {"s": source}).mappings().first()

    floor = date.fromisoformat(CLOSURE_SEED_FLOOR)
    if not row or not row["high_water_issue_date"]:
        # Lần đầu: quét về tận sàn cố định để dựng nền, không dùng cửa sổ trượt.
        return floor, "lan_dau_quet_ve_san"

    high = date.fromisoformat(str(row["high_water_issue_date"]))
    overlap = int(row["overlap_days"] or CRAWL_OVERLAP_DAYS)
    cutoff = high - timedelta(days=overlap)
    return max(cutoff, floor), f"watermark_{high}_lui_{overlap}_ngay"


def update_crawl_watermark(
    session: Session, source: str, high_water: date | None
) -> None:
    """Ghi lại mốc issueDate mới nhất đã thấy. Không lùi watermark."""
    from sqlalchemy import text as _text

    if not high_water:
        return
    session.execute(_text("""
        INSERT INTO crawl_watermark
            (source, high_water_issue_date, low_water_issue_date, last_run_at, overlap_days)
        VALUES (:s, :hw, :lw, datetime('now'), :ov)
        ON CONFLICT(source) DO UPDATE SET
            high_water_issue_date = MAX(
                COALESCE(crawl_watermark.high_water_issue_date, '0001-01-01'),
                excluded.high_water_issue_date
            ),
            last_run_at = datetime('now')
    """), {
        "s": source, "hw": high_water.isoformat(),
        "lw": CLOSURE_SEED_FLOOR, "ov": CRAWL_OVERLAP_DAYS,
    })


def insert_references(
    session: Session, source_doc_id: int, references: list[dict]
) -> int:
    """Insert document reference edges. Returns count inserted.

    Giải luôn target_doc_id khi văn bản đích đã có trong kho, nếu không đồ thị
    chỉ là các số hiệu rời không nối được với nhau.
    """
    count = 0
    for ref in references:
        target_moj_id = ref.get("target_moj_id") or None
        # id của văn bản đích được ghi lại kể cả khi cạnh đã tồn tại: các cạnh
        # tạo trước khi parse_doc_detail giữ id đều đang thiếu trường này.
        remember_moj_id(session, ref["target_doc_num"], target_moj_id, "reference")

        stmt = select(DocumentReference).where(
            DocumentReference.source_doc_id == source_doc_id,
            DocumentReference.target_doc_num == ref["target_doc_num"],
            DocumentReference.relation_type == ref["relation_type"],
        )
        existing_edge = session.execute(stmt).scalar_one_or_none()
        if existing_edge is None:
            target = get_document_by_doc_num(session, ref["target_doc_num"])
            edge = DocumentReference(
                source_doc_id=source_doc_id,
                target_doc_num=ref["target_doc_num"],
                relation_type=ref["relation_type"],
                target_doc_id=target.id if target else None,
                target_moj_id=target_moj_id,
            )
            session.add(edge)
            count += 1
        elif target_moj_id and not existing_edge.target_moj_id:
            existing_edge.target_moj_id = target_moj_id
    return count


def remember_moj_id(
    session: Session, doc_num: str, moj_id: str | None, source: str
) -> bool:
    """Ghi nhớ cặp số hiệu → id MOJ. True nếu là cặp mới.

    Endpoint /doc/all bỏ qua mọi tham số lọc nên không có cách nào tra một văn
    bản theo số hiệu. Bảng này là đường duy nhất để biết id của văn bản được dẫn
    chiếu mà kho chưa có — nó thay cho file cache data/moj_target_ids.json vốn
    phải nạp cả file vào bộ nhớ và không truy vấn kèm điều kiện được.
    """
    doc_num = (doc_num or "").strip()
    moj_id = (moj_id or "").strip()
    if not doc_num or not moj_id:
        return False

    exists = session.get(MojIdIndex, {"doc_num": doc_num, "moj_id": moj_id})
    if exists is not None:
        return False
    session.add(MojIdIndex(doc_num=doc_num, moj_id=moj_id, source=source))
    return True


def resolve_reference_targets(session: Session) -> int:
    """Nối lại các cạnh đang treo với văn bản đích vừa được thu thập.

    Cạnh được tạo trước khi văn bản đích về kho sẽ có target_doc_id NULL mãi
    mãi nếu không có bước này. Trả về số cạnh nối thêm hoặc sửa lại.

    Nối bằng `target_moj_id` TRƯỚC, số hiệu chỉ là phương án dự phòng. Bản trước
    chỉ dò theo số hiệu, hỏng theo hai hướng ngược nhau:

      - Không nối được khi chuỗi số hiệu lệch (khoảng trắng, dấu nháy, tiền tố
        "Số ..."), dù payload đã ghi sẵn id chính xác của đích. 199 văn bản nền
        vì thế không có cạnh vào nào, nên không tính được độ sâu bao đóng.
      - Nối bằng suy diễn khi hai văn bản trùng số hiệu: get_document_by_doc_num
        trả về một bản bất kỳ trong nhóm.

    XOÁ LIÊN KẾT khi có bằng chứng nó chỉ là suy diễn mà số hiệu lại không đủ
    định danh. Cụ thể: payload ghi một moj_id, văn bản đang được trỏ tới mang
    moj_id khác, và đó là văn bản CẤP TỈNH.

    Với văn bản trung ương thì không xoá, vì số hiệu trung ương duy nhất toàn
    quốc nên liên kết vẫn đúng văn bản — lệch id chỉ là do Bộ Tư pháp cấp nhiều
    id cho cùng một văn bản (đo được 198 cạnh như vậy; rõ nhất là Luật
    71/2014/QH13 tồn tại dưới cả "40742" lẫn "vbpqta_11034", hai hệ id khác
    nhau). Với cấp tỉnh thì trùng số hiệu là chuyện thường, nên 19 cạnh còn lại
    không chứng minh được là đúng.

    Trả về cạnh treo còn hơn cạnh sai: đích đã bị bỏ liên kết sẽ vào hàng đợi
    bao đóng theo đúng moj_id của nó, và tự nối lại đúng khi văn bản về kho.
    """
    # Số hiệu trùng nhiều cơ quan thì không dò theo số hiệu được nữa.
    trung = {
        row[0] for row in session.query(Document.doc_num)
        .group_by(Document.doc_num)
        .having(func.count(Document.id) > 1)
        .all()
    }
    id_theo_moj: dict[str, int] = {}
    ho_so: dict[int, tuple[str | None, str | None]] = {}
    for doc_id, moj_id, scope in session.query(
        Document.id, Document.moj_id, Document.territorial_scope
    ).all():
        if moj_id:
            id_theo_moj[moj_id] = doc_id
        ho_so[doc_id] = (moj_id, scope)

    edges = (
        session.query(DocumentReference)
        .filter(
            (DocumentReference.target_doc_id.is_(None))
            | (DocumentReference.target_moj_id.isnot(None))
        )
        .all()
    )
    resolved = 0
    for edge in edges:
        dung = id_theo_moj.get(edge.target_moj_id) if edge.target_moj_id else None

        if dung is None and edge.target_doc_id is None:
            if edge.target_doc_num in trung:
                continue
            target = get_document_by_doc_num(session, edge.target_doc_num)
            dung = target.id if target is not None else None

        if dung is None and edge.target_doc_id is not None and edge.target_moj_id:
            # Đích đúng chưa có trong kho, mà liên kết hiện tại lại mang moj_id
            # khác — chỉ giữ nếu số hiệu đủ định danh (văn bản trung ương).
            moj_hien_tai, scope = ho_so.get(edge.target_doc_id, (None, None))
            if moj_hien_tai and moj_hien_tai != edge.target_moj_id and scope == "tinh":
                edge.target_doc_id = None
                resolved += 1
            continue

        if dung is not None and dung != edge.target_doc_id:
            edge.target_doc_id = dung
            resolved += 1
    return resolved


def insert_status_change(
    session: Session,
    document_id: int,
    old_status: str | None,
    new_status: str,
    detected_by: str,
) -> None:
    """Record a status change event (event type B)."""
    entry = DocumentStatusHistory(
        document_id=document_id,
        old_status=old_status,
        new_status=new_status,
        detected_by=detected_by,
    )
    session.add(entry)


# ──────────────────────────────────────────────
# CrawlRun CRUD
# ──────────────────────────────────────────────
def create_crawl_run(session: Session) -> CrawlRun:
    """Start a new crawl run entry."""
    run = CrawlRun(
        run_date=date.today(),
        started_at=datetime.now(timezone.utc),
        status="RUNNING",
    )
    session.add(run)
    session.flush()
    return run


def finish_crawl_run(
    session: Session,
    run: CrawlRun,
    status: str = "SUCCESS",
    error_message: str | None = None,
    **metrics: int,
) -> None:
    """Mark a crawl run as finished with metrics."""
    run.finished_at = datetime.now(timezone.utc)
    run.status = status
    run.error_message = error_message
    for key, value in metrics.items():
        if hasattr(run, key):
            setattr(run, key, value)


def get_unnotified_documents(session: Session) -> list[Document]:
    """Get documents that haven't been sent via Telegram yet."""
    stmt = (
        select(Document)
        .where(Document.notified_at.is_(None))
        .where(Document.event_type.isnot(None))
        .order_by(Document.issue_date.desc())
    )
    return list(session.execute(stmt).scalars().all())
