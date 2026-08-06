"""
SQLAlchemy ORM models — mirrors the database schema from implementation plan.

Tables:
  - documents:               Master Record for each legal document
  - document_references:      Relationship graph edges (from MOJ references[])
  - document_status_history:  Effectiveness status change log (event B)
  - crawl_runs:               Pipeline execution log
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    """Master Record — one row per unique legal document (by doc_num)."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Số hiệu KHÔNG duy nhất toàn quốc: 63 tỉnh đánh số độc lập nên
    # "67/2026/QĐ-UBND" tồn tại ở 18 tỉnh khác nhau. Ràng buộc UNIQUE cũ khiến
    # bản thứ hai trở đi bị coi là "đã biết" và bị bỏ qua im lặng — đo trên một
    # lần quét 6.906 văn bản thì 4.211 bản sẽ bị nuốt.
    doc_num = Column(String(100), nullable=False, comment="Số hiệu VB")
    doc_key = Column(
        String(300),
        unique=True,
        nullable=False,
        comment="Định danh thật: số hiệu + cơ quan ban hành",
    )
    title = Column(Text, nullable=False)
    doc_type = Column(String(100), comment="Loại VB: Nghị định, Thông tư…")
    issue_date = Column(Date, comment="Ngày ban hành")
    pub_date = Column(
        Date,
        comment="Ngày TVPL đăng tin — dùng xếp thư mục khi chưa rõ ngày ban hành",
    )
    eff_from = Column(Date, comment="Ngày có hiệu lực")
    eff_to = Column(Date, nullable=True, comment="Ngày hết hiệu lực")
    eff_status = Column(
        String(50), comment="Còn hiệu lực / Hết hiệu lực / Chưa có hiệu lực"
    )
    agency_name = Column(String(255), comment="Cơ quan ban hành")
    signer = Column(String(255), comment="Người ký")
    field_name = Column(String(100), comment="Lĩnh vực")
    field_code = Column(Integer, comment="Mã lĩnh vực TVPL")

    # Source flags
    source_tvpl = Column(Boolean, default=False)
    source_moj = Column(Boolean, default=False)
    tvpl_id = Column(String(50), comment="ID trên TVPL (số cuối slug URL)")
    moj_id = Column(String(50), comment="ID trên MOJ API")
    tvpl_url = Column(Text)
    moj_url = Column(Text)

    # File flags
    has_docx = Column(Boolean, default=False)
    has_fulltext = Column(Boolean, default=False)
    has_chunks = Column(Boolean, default=False, comment="Đã tách Điều/Khoản")
    docx_path = Column(Text)
    fulltext_path = Column(Text)
    clean_text_path = Column(Text, comment="Clean Markdown path")
    chunks_path = Column(Text, comment="Legal chunks JSON path")

    # Google Drive & Lark Drive links
    gdrive_docx_link = Column(Text)
    gdrive_folder_id = Column(String(100))
    lark_docx_link = Column(Text)
    lark_folder_token = Column(String(100))


    # Phase 2: Obsidian
    industries = Column(String(500), comment="Phân loại ngành nghề")
    obsidian_path = Column(Text, comment="Đường dẫn file Obsidian")
    obsidian_hash = Column(String(64), comment="SHA-256 nội dung Obsidian để sync")

    # Event tracking
    event_type = Column(
        String(1), comment="A=mới, B=đổi hiệu lực, C=sửa/thay thế"
    )
    notified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    outgoing_refs = relationship(
        "DocumentReference",
        back_populates="source_doc",
        foreign_keys="DocumentReference.source_doc_id",
    )
    status_history = relationship("DocumentStatusHistory", back_populates="document")

    __table_args__ = (
        Index("idx_documents_doc_num", "doc_num"),
        Index("idx_documents_issue_date", "issue_date"),
        Index("idx_documents_field_code", "field_code"),
        Index("idx_documents_event_type", "event_type"),
        # Tra theo id nguồn là đường dedupe chính khi upsert; thiếu index thì
        # mỗi văn bản mới phải quét toàn bảng.
        Index("idx_documents_moj_id", "moj_id"),
        Index("idx_documents_tvpl_id", "tvpl_id"),
        Index("idx_documents_eff_status", "eff_status"),
    )


class DocumentReference(Base):
    """Relationship graph edge — document A modifies/replaces/guides B."""

    __tablename__ = "document_references"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_doc_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    target_doc_num = Column(
        String(100), nullable=False, comment="Số hiệu VB đích"
    )
    relation_type = Column(
        String(50),
        nullable=False,
        comment="Sửa đổi / Thay thế / Hướng dẫn / Bãi bỏ",
    )
    target_doc_id = Column(
        Integer, ForeignKey("documents.id"), nullable=True,
        comment="FK nếu VB đích đã có trong DB",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source_doc = relationship(
        "Document", back_populates="outgoing_refs", foreign_keys=[source_doc_id]
    )


class DocumentStatusHistory(Base):
    """Effectiveness status change log — captures event type B."""

    __tablename__ = "document_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    old_status = Column(String(50))
    new_status = Column(String(50))
    changed_at = Column(DateTime(timezone=True), server_default=func.now())
    detected_by = Column(String(10), comment="TVPL hoặc MOJ")

    document = relationship("Document", back_populates="status_history")


class CrawlRun(Base):
    """Pipeline execution log — one row per daily run."""

    __tablename__ = "crawl_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(Date, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        String(20), default="RUNNING", comment="RUNNING / SUCCESS / FAILED"
    )

    # Metrics per source
    tvpl_new_found = Column(Integer, default=0)
    tvpl_downloaded = Column(Integer, default=0)
    moj_new_found = Column(Integer, default=0)
    moj_enriched = Column(Integer, default=0)

    # Aggregated
    total_new = Column(Integer, default=0)
    total_notified = Column(Integer, default=0)
    gdrive_uploaded = Column(Integer, default=0)

    error_message = Column(Text, nullable=True)
    log_path = Column(Text, nullable=True)

    __table_args__ = (Index("idx_crawl_runs_date", "run_date"),)
