"""
Database connection & CRUD operations.

Supports both SQLite (dev) and PostgreSQL (production) via DATABASE_URL.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime
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
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized.")


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
def get_document_by_doc_num(session: Session, doc_num: str) -> Document | None:
    """Find a document by its standardized doc_num."""
    stmt = select(Document).where(Document.doc_num == doc_num)
    return session.execute(stmt).scalar_one_or_none()


def get_document_by_moj_id(session: Session, moj_id: str) -> Document | None:
    """Find a document by its MOJ internal ID."""
    stmt = select(Document).where(Document.moj_id == moj_id)
    return session.execute(stmt).scalar_one_or_none()


def get_document_by_tvpl_id(session: Session, tvpl_id: str) -> Document | None:
    """Find a document by its TVPL ID (last slug number)."""
    stmt = select(Document).where(Document.tvpl_id == tvpl_id)
    return session.execute(stmt).scalar_one_or_none()


def upsert_document(session: Session, data: dict) -> tuple[Document, bool]:
    """
    Insert or update a document by doc_num.
    Returns (document, is_new).
    """
    doc_num = data.get("doc_num", "")
    existing = get_document_by_doc_num(session, doc_num)

    if existing:
        # Update fields that are not yet populated
        for key, value in data.items():
            if value is not None:
                current = getattr(existing, key, None)
                # Don't overwrite existing truthy values with falsy ones
                if current is None or current == "" or current is False:
                    setattr(existing, key, value)
                elif key in ("source_tvpl", "source_moj") and value is True:
                    setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
        return existing, False
    else:
        doc = Document(**data)
        session.add(doc)
        session.flush()  # Get the auto-generated ID
        return doc, True


def insert_references(
    session: Session, source_doc_id: int, references: list[dict]
) -> int:
    """Insert document reference edges. Returns count inserted."""
    count = 0
    for ref in references:
        # Check if this exact edge already exists
        stmt = select(DocumentReference).where(
            DocumentReference.source_doc_id == source_doc_id,
            DocumentReference.target_doc_num == ref["target_doc_num"],
            DocumentReference.relation_type == ref["relation_type"],
        )
        if session.execute(stmt).scalar_one_or_none() is None:
            edge = DocumentReference(
                source_doc_id=source_doc_id,
                target_doc_num=ref["target_doc_num"],
                relation_type=ref["relation_type"],
            )
            session.add(edge)
            count += 1
    return count


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
        started_at=datetime.utcnow(),
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
    run.finished_at = datetime.utcnow()
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
