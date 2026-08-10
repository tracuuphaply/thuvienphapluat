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
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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
    field_code = Column(Integer, comment="Mã lĩnh vực TVPL, chỉ có khi TVPL gán")
    # Lĩnh vực TVPL đã giải quyết cho MỌI văn bản. Tách khỏi field_code vì cột
    # kia là dữ kiện còn cột này một phần là suy đoán — tvpl_field_source nói
    # rõ đến từ đâu, để không ai đọc suy đoán như dữ kiện.
    tvpl_field_code = Column(Integer, comment="Mã lĩnh vực TVPL 1-27, luôn có")
    tvpl_field_source = Column(
        String(20), comment="tvpl | moj_map | tu_khoa | khac")

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

    # ── Dữ kiện pháp lý suy được (src/legal/) ──
    # Thành cột riêng để lọc được ở tầng SQL. Suy lại ở từng chỗ dùng nghĩa là
    # phải tải dư dữ liệu về rồi mới loại, và không đánh chỉ mục được.
    hierarchy_level = Column(
        Integer, comment="1..9 theo Điều 4 Luật BHVBQPPL 2025; 99 = không phải VBQPPL"
    )
    doc_type_norm = Column(String(50), comment="Loại chuẩn hoá: luat, nghi_dinh…")
    is_vbqppl = Column(Boolean, comment="Là văn bản quy phạm pháp luật")
    territorial_scope = Column(String(20), comment="trung_uong | tinh | khong_xac_dinh")
    province_code_raw = Column(String(40), comment="Mã tỉnh như văn bản ghi")
    province_code_current = Column(
        String(40), comment="Mã tỉnh sau sắp xếp 2025 (NQ 202/2025/QH15)"
    )
    eff_state = Column(String(30), comment="Cờ hiệu lực chuẩn hoá")
    eff_state_as_of = Column(
        Date, comment="Mốc tính cờ — cờ không có mốc là khẳng định sai từ hôm sau"
    )
    eff_state_source = Column(String(20), comment="trang_thai | ngay_thang | khong_ro")

    # ── Bao đóng dẫn chiếu ──
    is_closure_node = Column(
        Boolean, comment="Vào kho vì bị dẫn chiếu, không phải vì thuộc lĩnh vực DN"
    )
    first_seen_depth = Column(Integer, comment="Độ sâu bao đóng lúc phát hiện")

    # Google Drive & Lark Drive links
    gdrive_docx_link = Column(Text)
    gdrive_fulltext_link = Column(Text)
    gdrive_folder_id = Column(String(100))
    lark_docx_link = Column(Text)
    lark_fulltext_link = Column(Text)
    lark_folder_token = Column(String(100))
    cloud_synced_at = Column(
        DateTime(timezone=True),
        comment="Đã lên cloud; chưa có thì không được xoá file local",
    )


    # Phase 2: Obsidian
    industries = Column(String(500), comment="Phân loại ngành nghề")
    obsidian_path = Column(Text, comment="Đường dẫn file Obsidian")
    obsidian_hash = Column(String(64), comment="SHA-256 nội dung Obsidian để sync")

    # Định danh dùng cho tên file vault và URL công khai. Số hiệu trần không đủ:
    # "40/2026/QĐ-UBND" tồn tại ở nhiều tỉnh nên hai note sẽ trùng tên và note
    # sau ghi đè note trước mà không báo gì.
    public_slug = Column(
        String(160), unique=True, nullable=True,
        comment="Slug duy nhất: số hiệu + mã tỉnh, ví dụ 40-2026-QD-UBND--79",
    )
    published_hash = Column(
        String(64), nullable=True,
        comment="SHA-256 bản đã đẩy lên trang công khai; NULL = chưa công khai",
    )

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
        # Lọc theo cấp/địa bàn/hiệu lực là đường truy xuất chính của báo cáo;
        # thiếu chỉ mục thì mỗi lần lọc phải quét toàn bảng.
        Index("idx_documents_hierarchy_level", "hierarchy_level"),
        Index("idx_documents_province_code_current", "province_code_current"),
        Index("idx_documents_eff_state", "eff_state"),
        Index("idx_documents_is_vbqppl", "is_vbqppl"),
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
    # Gateway trả sẵn references[].targetDocument.id. Endpoint /doc/all bỏ qua
    # mọi tham số lọc nên không tra ngược số hiệu ra id được — đây là đường duy
    # nhất để tải văn bản được dẫn chiếu mà kho chưa có.
    target_moj_id = Column(
        String(50), nullable=True, comment="ID trên MOJ của VB đích, nếu payload có"
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source_doc = relationship(
        "Document", back_populates="outgoing_refs", foreign_keys=[source_doc_id]
    )

    __table_args__ = (
        Index("idx_refs_target_moj_id", "target_moj_id"),
    )


class MojIdIndex(Base):
    """Tra số hiệu → id MOJ, thay cho file cache data/moj_target_ids.json.

    Mỗi lần fetch chi tiết đều đi kèm danh sách targetDocument có id; gom vào
    đây để crawler bao đóng biết đường tải văn bản chưa có, thay vì phải quét
    lại toàn kho chỉ để thu thập id.
    """

    __tablename__ = "moj_id_index"

    doc_num = Column(String(100), primary_key=True)
    moj_id = Column(String(50), primary_key=True)
    source = Column(String(20), nullable=False, comment="reference | scan | detail")
    first_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_moj_id_index_moj_id", "moj_id"),)


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


class UploadQueue(Base):
    """Văn bản chờ đẩy lên mây sau khi upload thất bại.

    Không có bảng này thì upload hỏng chỉ để lại một dòng log: văn bản không bao
    giờ được thử lại và cũng không ai biết nó thiếu trên Drive. Ràng buộc duy
    nhất (doc_key, provider) để lần hỏng sau cập nhật mục cũ thay vì chất đống.
    """

    __tablename__ = "upload_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_key = Column(String(300), nullable=False)
    doc_num = Column(String(100))
    provider = Column(String(20), nullable=False, comment="gdrive | lark | both")
    file_kinds = Column(Text, nullable=False, comment="Các loại file còn thiếu")
    status = Column(String(20), nullable=False, default="PENDING")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_upload_queue_doc", "doc_key", "provider", unique=True),
        Index("idx_upload_queue_status", "status"),
    )


class DocumentIndustryImpact(Base):
    """Điểm tác động của một văn bản lên một ngành VSIC.

    `scorer_version` nằm trong khoá chính là thứ làm hệ thống tái lập được: chạy
    lại cùng version luôn ra đúng số cũ, và version mới sống song song để đối
    chiếu thay vì ghi đè dữ liệu đã dùng trong báo cáo đã phát hành.

    Lưu cả đầu vào thô chứ không chỉ kết quả: một tỷ lệ phần trăm không kèm đầu
    vào thì không kiểm toán được khi khách hỏi vì sao ra con số đó.
    """

    __tablename__ = "document_industry_impact"

    doc_key = Column(String(300), primary_key=True)
    vsic_code = Column(String(4), primary_key=True)
    scorer_version = Column(String(60), primary_key=True)
    doc_num = Column(String(100))
    restriction_weighted = Column(Float, comment="Tổng ràng buộc có trọng số của VB")
    relevance_lexicon = Column(Float)
    relevance_embedding = Column(Float)
    relevance_fused = Column(Float)
    impact_raw = Column(Float)
    impact_pct_doc = Column(Float, comment="Tổng 21 ngành = 100%: tác động tới AI")
    impact_pct_industry = Column(
        Float, comment="Phân vị so toàn kho: ngành nên quan tâm TỚI MỨC NÀO"
    )
    computed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_impact_industry", "vsic_code", "scorer_version", "impact_pct_industry"),
        Index("idx_impact_doc", "doc_num", "scorer_version"),
    )


class IndustryProfile(Base):
    """Hồ sơ ngành và tham số hiệu chuẩn, ĐÓNG BĂNG theo scorer_version.

    Nhúng lại cùng một câu trên model đang trôi sẽ làm điểm số đổi thầm lặng —
    vì vậy vector hồ sơ, vector tâm và (mean, sd) đều được lưu chứ không tính lại.
    """

    __tablename__ = "industry_profile"

    vsic_code = Column(String(4), primary_key=True)
    scorer_version = Column(String(60), primary_key=True)
    embedding = Column(LargeBinary, comment="Vector hồ sơ ngành, đã trừ tâm")
    corpus_mean = Column(LargeBinary, comment="Vector tâm toàn kho")
    mean = Column(Float, comment="Trung bình cosine của ngành trên mẫu kho")
    sd = Column(Float, comment="Độ lệch chuẩn, dùng chuẩn hoá z")
    built_from = Column(Text, comment="JSON các câu đã nhúng để dựng hồ sơ")
    built_at = Column(DateTime(timezone=True), server_default=func.now())


class ReportJob(Base):
    """Một báo cáo chờ sinh.

    Báo cáo được XẾP HÀNG ở cuối lần cào chứ không sinh tại chỗ: gọi mô hình mất
    tới 300 giây và lời gọi đó sẽ nằm trong khối try bao trọn pipeline, nên một
    lỗi LLM đánh dấu cả lần cào là FAILED — kéo theo run_daily.sh bỏ luôn hai
    bước đồng bộ vault và RAG.
    """

    __tablename__ = "report_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(1), nullable=False, comment="a=ngành, b=văn bản mới, c=doanh nghiệp")
    status = Column(
        String(20), nullable=False, default="QUEUED",
        comment="QUEUED | RUNNING | DONE | FAILED | BLOCKED_CITATION | SKIPPED",
    )
    vsic_code = Column(String(4))
    industry = Column(String(120))
    subject_keys = Column(Text, comment="JSON danh sách doc_key cần phân tích")
    parent_job_id = Column(Integer, comment="Báo cáo (c) trỏ về báo cáo (b) gốc")
    trigger_reason = Column(String(80))
    # Gộp mọi văn bản mới của một ngành trong một ngày vào MỘT báo cáo — cơ chế
    # chống ngập quan trọng nhất.
    dedupe_key = Column(String(200), nullable=False, unique=True)
    priority = Column(Float, nullable=False, default=0)
    scheduled_for = Column(String(10), comment="Dời sang hôm sau khi chạm trần ngày")
    started_at = Column(String(30))
    finished_at = Column(String(30))
    output_md_path = Column(Text)
    output_pdf_path = Column(Text)
    output_json_path = Column(Text, comment="Sidecar máy đọc được để (c) tiêu thụ")
    citation_total = Column(Integer)
    citation_missing = Column(Integer)
    model = Column(String(60))
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_report_jobs_pick", "status", "priority", "scheduled_for"),
    )


class CrawlWatermark(Base):
    """Mốc đã quét tới của mỗi nguồn.

    Thay cửa sổ trượt: cutoff cũ tính bằng `today - 30 ngày` nên mỗi lần chạy
    quét lại toàn bộ cửa sổ, và máy tắt lâu hơn 30 ngày là mất hẳn phần ở giữa.
    """

    __tablename__ = "crawl_watermark"

    source = Column(String(20), primary_key=True)
    high_water_issue_date = Column(Date, comment="issueDate mới nhất đã thấy")
    low_water_issue_date = Column(Date, comment="Sàn quét, không trôi theo ngày chạy")
    last_run_at = Column(DateTime(timezone=True))
    overlap_days = Column(
        Integer, nullable=False, default=45,
        comment="Quét lùi quá watermark, vì văn bản được đăng muộn hơn ngày ban hành",
    )


class CrawlFrontier(Base):
    """Hàng đợi bao đóng dẫn chiếu.

    Phải nằm trong cơ sở dữ liệu chứ không trong bộ nhớ: bao đóng chạy hàng giờ
    tới hàng ngày, đứt giữa chừng mà mất hàng đợi thì mọi lần chạy đều bắt đầu
    lại từ đầu.
    """

    __tablename__ = "crawl_frontier"

    moj_id = Column(String(50), primary_key=True)
    doc_num = Column(String(100))
    depth = Column(Integer, nullable=False, default=0)
    priority = Column(Float, nullable=False, default=0)
    state = Column(
        String(20), nullable=False, default="PENDING",
        comment="PENDING | DONE | FAILED | NO_ID | HUB_NOT_EXPANDED",
    )
    discovered_from = Column(String(100), comment="Số hiệu văn bản dẫn tới đây")
    discovered_via_relation = Column(String(50))
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_frontier_pick", "state", "priority", "depth"),
    )


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
