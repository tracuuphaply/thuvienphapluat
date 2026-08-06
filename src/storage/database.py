"""
Database connection & CRUD operations.

Supports both SQLite (dev) and PostgreSQL (production) via DATABASE_URL.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Generator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.config import DATABASE_URL
from src.storage.models import (
    Base,
    CrawlRun,
    Document,
    DocumentReference,
    DocumentStatusHistory,
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
    """Create all tables if they don't exist and add missing columns."""
    Base.metadata.create_all(bind=engine)

    # Auto-add missing columns to existing SQLite table if needed
    with engine.connect() as conn:
        from sqlalchemy import text
        existing_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(documents)"))
        }
        for col, col_type in [
            ("lark_docx_link", "TEXT"),
            ("lark_folder_token", "VARCHAR(100)"),
            ("pub_date", "DATE"),
            ("industries", "VARCHAR(500)"),
            ("obsidian_path", "TEXT"),
            ("obsidian_hash", "VARCHAR(64)"),
            ("doc_key", "VARCHAR(300)"),
        ]:
            if col in existing_cols:
                continue
            try:
                conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col} {col_type};"))
                conn.commit()
                logger.info("Migrated DB: added column %s to documents", col)
            except Exception as e:
                # Không nuốt im lặng: đây là lỗi thật, không phải "cột đã tồn tại"
                # (trường hợp đó đã được lọc ở trên bằng PRAGMA table_info).
                logger.error("Không thêm được cột %s: %s", col, e)

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
    """Find a document by its MOJ internal ID."""
    stmt = select(Document).where(Document.moj_id == moj_id)
    return session.execute(stmt).scalar_one_or_none()


def get_document_by_tvpl_id(session: Session, tvpl_id: str) -> Document | None:
    """Find a document by its TVPL ID (last slug number)."""
    stmt = select(Document).where(Document.tvpl_id == tvpl_id)
    return session.execute(stmt).scalar_one_or_none()


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
        existing.doc_key = make_doc_key(existing.doc_num, existing.agency_name)

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

        existing.updated_at = datetime.now(timezone.utc)
        return existing, False
    else:
        payload = dict(data)
        payload["doc_key"] = make_doc_key(doc_num, payload.get("agency_name"))
        doc = Document(**payload)
        session.add(doc)
        session.flush()  # Get the auto-generated ID
        return doc, True


def insert_references(
    session: Session, source_doc_id: int, references: list[dict]
) -> int:
    """Insert document reference edges. Returns count inserted.

    Giải luôn target_doc_id khi văn bản đích đã có trong kho, nếu không đồ thị
    chỉ là các số hiệu rời không nối được với nhau.
    """
    count = 0
    for ref in references:
        # Check if this exact edge already exists
        stmt = select(DocumentReference).where(
            DocumentReference.source_doc_id == source_doc_id,
            DocumentReference.target_doc_num == ref["target_doc_num"],
            DocumentReference.relation_type == ref["relation_type"],
        )
        if session.execute(stmt).scalar_one_or_none() is None:
            target = get_document_by_doc_num(session, ref["target_doc_num"])
            edge = DocumentReference(
                source_doc_id=source_doc_id,
                target_doc_num=ref["target_doc_num"],
                relation_type=ref["relation_type"],
                target_doc_id=target.id if target else None,
            )
            session.add(edge)
            count += 1
    return count


def resolve_reference_targets(session: Session) -> int:
    """Nối lại các cạnh đang treo với văn bản đích vừa được thu thập.

    Cạnh được tạo trước khi văn bản đích về kho sẽ có target_doc_id NULL mãi
    mãi nếu không có bước này. Trả về số cạnh nối được thêm.
    """
    pending = (
        session.query(DocumentReference)
        .filter(DocumentReference.target_doc_id.is_(None))
        .all()
    )
    resolved = 0
    for edge in pending:
        target = get_document_by_doc_num(session, edge.target_doc_num)
        if target is not None:
            edge.target_doc_id = target.id
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
