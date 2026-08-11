"""
Migration có ghi lịch sử cho SQLite.

Trước đây việc đổi lược đồ nằm rải ở ba chỗ, không chỗ nào ghi lại đã chạy gì:
  - vòng lặp ADD COLUMN hardcode trong database.init_db()
  - _ensure_doc_key() vừa điền dữ liệu vừa tạo chỉ mục
  - scripts/migrate_doc_key.py dựng lại bảng 12 bước

Hệ quả là không trả lời được câu "cơ sở dữ liệu này đang ở phiên bản nào", và
mỗi lần khởi động lại chạy lại toàn bộ ALTER dù đã có cột. Module này thay phần
đó bằng một danh sách có thứ tự, mỗi bước chạy đúng một lần và được ghi vào bảng
`schema_migrations`.

Nguyên tắc khi thêm migration mới:
  - id không bao giờ đổi và không bao giờ dùng lại, kể cả khi migration bị sửa
  - hàm phải chạy được nhiều lần mà không hỏng (idempotent), vì một lần chạy dở
    có thể đã áp dụng được một nửa trước khi lỗi
  - migration cần gỡ ràng buộc thì KHÔNG viết ở đây: SQLite không DROP
    CONSTRAINT, phải dựng lại bảng theo quy trình 12 bước ở
    scripts/migrate_doc_key.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    id: str
    description: str
    run: Callable[[Connection], None]


# ──────────────────────────────────────────────
# Tiện ích
# ──────────────────────────────────────────────
def table_columns(conn: Connection, table: str) -> set[str]:
    """Tên các cột hiện có của một bảng; rỗng nếu bảng chưa tồn tại."""
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def add_column(conn: Connection, table: str, column: str, ddl_type: str) -> bool:
    """Thêm cột nếu chưa có. True nếu vừa thêm.

    Không nuốt lỗi: đã lọc trường hợp "cột đã tồn tại" bằng PRAGMA ở trên, nên
    mọi ngoại lệ còn lại là lỗi thật và phải nổi lên.
    """
    if column in table_columns(conn, table):
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
    logger.info("Migration: thêm cột %s.%s", table, column)
    return True


def _add_columns(conn: Connection, table: str, columns: list[tuple[str, str]]) -> None:
    for name, ddl in columns:
        add_column(conn, table, name, ddl)


# ──────────────────────────────────────────────
# Các bước migration, theo thứ tự
# ──────────────────────────────────────────────
def _m001_legacy_document_columns(conn: Connection) -> None:
    """Các cột từng được thêm bằng vòng lặp hardcode trong init_db().

    Giữ lại nguyên danh sách để cơ sở dữ liệu cũ nâng cấp được, còn cơ sở dữ
    liệu mới thì Base.metadata.create_all() đã tạo sẵn nên bước này không làm gì.
    """
    _add_columns(conn, "documents", [
        ("lark_docx_link", "TEXT"),
        ("lark_folder_token", "VARCHAR(100)"),
        ("pub_date", "DATE"),
        ("industries", "VARCHAR(500)"),
        ("obsidian_path", "TEXT"),
        ("obsidian_hash", "VARCHAR(64)"),
        ("doc_key", "VARCHAR(300)"),
    ])


def _m002_public_slug(conn: Connection) -> None:
    """Định danh dùng cho tên file vault và URL công khai.

    Tên note hiện lấy từ sanitize_filename(doc_num). Kể từ khi định danh chuyển
    sang doc_key, hai tỉnh có thể cùng tồn tại với số hiệu "40/2026/QĐ-UBND" —
    note thứ hai sẽ ghi đè note thứ nhất mà không báo gì. public_slug gắn thêm
    phần phân biệt để hai văn bản đó ra hai file khác nhau.
    """
    add_column(conn, "documents", "public_slug", "VARCHAR(160)")
    add_column(conn, "documents", "published_hash", "VARCHAR(64)")
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_public_slug "
        "ON documents(public_slug) WHERE public_slug IS NOT NULL"
    ))


def _m003_reference_target_moj_id(conn: Connection) -> None:
    """Giữ lại id MOJ của văn bản đích trong mỗi cạnh dẫn chiếu.

    Gateway trả sẵn references[].targetDocument.id nhưng parse_doc_detail() cũ
    vứt đi, chỉ giữ số hiệu. Vì endpoint /doc/all bỏ qua mọi tham số lọc nên
    không có cách nào tra ngược số hiệu ra id — mất id nghĩa là mất luôn đường
    tải văn bản được dẫn chiếu. Đây là dữ liệu vốn đã nằm sẵn trong phản hồi.
    """
    add_column(conn, "document_references", "target_moj_id", "VARCHAR(50)")
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_refs_target_moj_id "
        "ON document_references(target_moj_id)"
    ))


def _m004_moj_id_index(conn: Connection) -> None:
    """Bảng tra số hiệu → id MOJ, thay cho file cache data/moj_target_ids.json.

    Đưa vào cơ sở dữ liệu để mọi lần fetch đều bồi thêm được, và để crawler bao
    đóng truy vấn kèm điều kiện thay vì nạp cả file vào bộ nhớ.
    """
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS moj_id_index (
            doc_num     VARCHAR(100) NOT NULL,
            moj_id      VARCHAR(50)  NOT NULL,
            source      VARCHAR(20)  NOT NULL,
            first_seen  TEXT         NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (doc_num, moj_id)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_moj_id_index_moj_id ON moj_id_index(moj_id)"
    ))


def _m005_legal_facts(conn: Connection) -> None:
    """Dữ kiện pháp lý suy được: thứ bậc, phạm vi lãnh thổ, cờ hiệu lực.

    Ba nhóm này trước đây phải suy lại ở từng chỗ dùng, bằng cách so chuỗi trong
    Python sau khi đã tải dữ liệu về. Thành cột có chỉ mục thì lọc được ngay ở
    câu SQL — điều kiện cần để truy xuất không bị văn bản đã hết hiệu lực chiếm
    chỗ sau khi kho lớn lên vì bao đóng dẫn chiếu.
    """
    _add_columns(conn, "documents", [
        ("hierarchy_level", "INTEGER"),
        ("doc_type_norm", "VARCHAR(50)"),
        ("is_vbqppl", "BOOLEAN"),
        ("territorial_scope", "VARCHAR(20)"),
        ("province_code_raw", "VARCHAR(40)"),
        ("province_code_current", "VARCHAR(40)"),
        ("eff_state", "VARCHAR(30)"),
        ("eff_state_as_of", "DATE"),
        ("eff_state_source", "VARCHAR(20)"),
        # Vào kho vì bị dẫn chiếu, không phải vì thuộc lĩnh vực doanh nghiệp.
        ("is_closure_node", "BOOLEAN"),
        ("first_seen_depth", "INTEGER"),
        # Cổng cho phép xoá file local: chưa lên Drive thì không được dọn.
        ("cloud_synced_at", "DATETIME"),
        ("gdrive_fulltext_link", "TEXT"),
        ("lark_fulltext_link", "TEXT"),
    ])
    for col in ("hierarchy_level", "province_code_current", "eff_state", "is_vbqppl"):
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_documents_{col} ON documents({col})"
        ))


def _m006_upload_queue(conn: Connection) -> None:
    """Hàng đợi upload — để upload hỏng không đồng nghĩa với mất file.

    Trước đây upload thất bại chỉ ghi một dòng log rồi đi tiếp; văn bản đó không
    bao giờ được thử lại và cũng không ai biết nó thiếu trên Drive. Kèm theo
    `documents.cloud_synced_at` làm cổng: chưa lên mây thì AUTO_CLEANUP không
    được phép xoá file local.
    """
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS upload_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_key     VARCHAR(300) NOT NULL,
            doc_num     VARCHAR(100),
            provider    VARCHAR(20)  NOT NULL,
            file_kinds  TEXT         NOT NULL,
            status      VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
            attempts    INTEGER      NOT NULL DEFAULT 0,
            last_error  TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """))
    # Mỗi văn bản chỉ một mục đang chờ cho mỗi đích lưu trữ; lần hỏng sau cập
    # nhật mục cũ thay vì chất đống bản trùng.
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_upload_queue_doc "
        "ON upload_queue(doc_key, provider)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_upload_queue_status ON upload_queue(status)"
    ))


def _m007_seed_cloud_synced_at(conn: Connection) -> None:
    """Đánh dấu đã đồng bộ cho văn bản vốn đã nằm trên Lark.

    Cổng "đã lên mây" trước đây được suy từ `lark_folder_token`. Đổi sang
    `cloud_synced_at` mà không chuyển dữ liệu cũ thì 314 văn bản đã upload thành
    công sẽ bị coi là chưa, và lần chạy `--upload-only` kế tiếp đẩy lại toàn bộ.

    Dùng `updated_at` làm mốc vì không lưu lại thời điểm upload thật; đây là xấp
    xỉ có chủ ý, ghi ra đây để sau này không ai đọc nhầm thành mốc chính xác.
    """
    conn.execute(text("""
        UPDATE documents
        SET cloud_synced_at = COALESCE(updated_at, datetime('now'))
        WHERE cloud_synced_at IS NULL AND lark_folder_token IS NOT NULL
    """))


def _m008_crawl_state(conn: Connection) -> None:
    """Watermark bền vững và hàng đợi bao đóng dẫn chiếu.

    `crawl_watermark` thay cửa sổ trượt: cutoff cũ tính bằng `today - 30 ngày`
    nên mỗi lần chạy quét lại toàn bộ cửa sổ (6.906 văn bản để tìm 50 bản mới),
    và máy tắt lâu hơn 30 ngày là mất hẳn phần ở giữa.

    `crawl_frontier` phải nằm trong cơ sở dữ liệu chứ không trong bộ nhớ: bao
    đóng chạy hàng giờ tới hàng ngày, đứt giữa chừng mà mất hàng đợi thì mọi lần
    chạy đều bắt đầu lại từ đầu.
    """
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS crawl_watermark (
            source                  VARCHAR(20) PRIMARY KEY,
            high_water_issue_date   DATE,
            low_water_issue_date    DATE,
            last_run_at             TEXT,
            overlap_days            INTEGER NOT NULL DEFAULT 45
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS crawl_frontier (
            moj_id                  VARCHAR(50) PRIMARY KEY,
            doc_num                 VARCHAR(100),
            depth                   INTEGER NOT NULL DEFAULT 0,
            priority                REAL    NOT NULL DEFAULT 0,
            state                   VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            discovered_from         VARCHAR(100),
            discovered_via_relation VARCHAR(50),
            attempts                INTEGER NOT NULL DEFAULT 0,
            last_error              TEXT,
            discovered_at           TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """))
    # Lấy việc tiếp theo = PENDING, ưu tiên cao nhất, nông nhất.
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_frontier_pick "
        "ON crawl_frontier(state, priority DESC, depth)"
    ))


def _m009_industry_impact(conn: Connection) -> None:
    """Điểm tác động của từng văn bản lên 21 ngành VSIC.

    `scorer_version` nằm trong khoá chính là thứ làm hệ thống TÁI LẬP được: chạy
    lại cùng version luôn ra đúng số cũ, và version mới sống song song để đối
    chiếu thay vì ghi đè dữ liệu đã dùng trong báo cáo đã phát hành.

    Lưu cả đầu vào thô (`restriction_weighted`, hai điểm liên quan) chứ không chỉ
    kết quả: một tỷ lệ phần trăm không kèm đầu vào thì không kiểm toán được khi
    khách hỏi vì sao ra con số đó.
    """
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS document_industry_impact (
            doc_key              VARCHAR(300) NOT NULL,
            doc_num              VARCHAR(100),
            vsic_code            VARCHAR(4)   NOT NULL,
            scorer_version       VARCHAR(60)  NOT NULL,
            restriction_weighted REAL,
            relevance_lexicon    REAL,
            relevance_embedding  REAL,
            relevance_fused      REAL,
            impact_raw           REAL,
            impact_pct_doc       REAL,
            impact_pct_industry  REAL,
            computed_at          TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (doc_key, vsic_code, scorer_version)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_impact_industry "
        "ON document_industry_impact(vsic_code, scorer_version, impact_pct_industry DESC)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_impact_doc "
        "ON document_industry_impact(doc_num, scorer_version)"
    ))

    # Hồ sơ ngành và các tham số hiệu chuẩn phải được ĐÓNG BĂNG: nhúng lại cùng
    # một câu trên model đang trôi sẽ làm điểm số đổi thầm lặng.
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS industry_profile (
            vsic_code       VARCHAR(4)  NOT NULL,
            scorer_version  VARCHAR(60) NOT NULL,
            embedding       BLOB,
            corpus_mean     BLOB,
            mean            REAL,
            sd              REAL,
            built_from      TEXT,
            built_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (vsic_code, scorer_version)
        )
    """))



def _m010_report_jobs(conn: Connection) -> None:
    """Hàng đợi sinh báo cáo.

    Báo cáo được XẾP HÀNG trong run_pipeline chứ không sinh tại chỗ. Lý do rất
    cụ thể: httpx.post(timeout=300) nằm trong khối try bao trọn pipeline, nên một
    lỗi LLM sẽ đánh dấu cả lần cào là FAILED — và khi đó run_daily.sh bỏ luôn hai
    bước đồng bộ vault và RAG. Một báo cáo hỏng không được phép làm hỏng ngày cào
    dữ liệu.

    `dedupe_key` là cơ chế chống ngập quan trọng nhất: khoá dạng
    "b:{ma_nganh}:{ngay}" gom mọi văn bản mới của một ngành trong một ngày vào
    MỘT báo cáo, thay vì mỗi văn bản một cái.
    """
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS report_jobs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            kind             VARCHAR(1)  NOT NULL,
            status           VARCHAR(20) NOT NULL DEFAULT 'QUEUED',
            vsic_code        VARCHAR(4),
            industry         VARCHAR(120),
            subject_keys     TEXT,
            parent_job_id    INTEGER,
            trigger_reason   VARCHAR(80),
            dedupe_key       VARCHAR(200) NOT NULL,
            priority         REAL NOT NULL DEFAULT 0,
            scheduled_for    TEXT,
            started_at       TEXT,
            finished_at      TEXT,
            output_md_path   TEXT,
            output_pdf_path  TEXT,
            output_json_path TEXT,
            citation_total   INTEGER,
            citation_missing INTEGER,
            model            VARCHAR(60),
            error            TEXT,
            created_at       TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_report_jobs_dedupe "
        "ON report_jobs(dedupe_key)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_report_jobs_pick "
        "ON report_jobs(status, priority DESC, scheduled_for)"
    ))


def _m011_tvpl_field(conn: Connection) -> None:
    """Lĩnh vực theo danh mục Thư viện Pháp luật, kèm nguồn của phân loại.

    Không ghi đè `field_code`: cột đó giữ mã do CHÍNH TVPL gán (1.448 văn bản),
    là dữ kiện. `tvpl_field_code` là kết quả đã giải quyết cho mọi văn bản, có
    thể đến từ suy đoán — nên `tvpl_field_source` đi kèm để phân biệt. Gộp hai
    thứ vào một cột thì về sau không ai biết đâu là dữ kiện, đâu là suy đoán.
    """
    _add_columns(conn, "documents", [
        ("tvpl_field_code", "INTEGER"),
        ("tvpl_field_source", "VARCHAR(20)"),
    ])
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_documents_tvpl_field "
        "ON documents(tvpl_field_code)"
    ))


def _m012_slug_chu_thuong(conn: Connection) -> None:
    """Hạ chữ thường mọi public_slug đã có.

    Quartz phát ra đường dẫn chữ thường, GitHub Pages phân biệt hoa/thường, nên
    slug dạng hoa làm mọi link trong phụ lục PDF trỏ tới 404. Phải chạy TRƯỚC
    khi trang công khai lên mạng: sau đó thì đổi slug là làm chết những URL đã
    in ra giấy, mà yêu cầu số 1 của public_slug là ổn định vĩnh viễn.

    DỪNG NẾU CÓ VA CHẠM. Cột có ràng buộc duy nhất phân biệt hoa/thường, nên
    hai slug chỉ khác nhau kiểu chữ vẫn lọt vào được; hạ chúng xuống sẽ vi phạm
    ràng buộc. Kiểm trước rồi báo lỗi rõ ràng còn hơn để UPDATE nổ giữa chừng
    với một nửa số dòng đã đổi. (Đo trên kho thật lúc viết: 4.467 slug, 0 va
    chạm.)
    """
    va = conn.execute(text(
        "SELECT LOWER(public_slug) s, COUNT(*) n FROM documents "
        "WHERE public_slug IS NOT NULL GROUP BY s HAVING n > 1"
    )).fetchall()
    if va:
        vi_du = ", ".join(r[0] for r in va[:5])
        raise RuntimeError(
            f"{len(va)} slug đụng nhau sau khi hạ chữ thường: {vi_du}. "
            f"Phải đặt lại slug cho các văn bản này trước khi chạy migration."
        )
    conn.execute(text(
        "UPDATE documents SET public_slug = LOWER(public_slug) "
        "WHERE public_slug IS NOT NULL AND public_slug <> LOWER(public_slug)"
    ))
    # published_hash về NULL: tên file trang công khai đổi theo slug, nên bản đã
    # đăng dưới tên cũ coi như chưa đăng. Không xoá thì bộ đăng trang bỏ qua
    # chúng vì hash nội dung không đổi, và link vẫn trỏ tới tên file cũ.
    conn.execute(text("UPDATE documents SET published_hash = NULL"))


MIGRATIONS: list[Migration] = [
    Migration("001_legacy_document_columns",
              "Các cột documents từng thêm bằng vòng lặp hardcode",
              _m001_legacy_document_columns),
    Migration("002_public_slug",
              "documents.public_slug + published_hash cho vault và trang công khai",
              _m002_public_slug),
    Migration("003_reference_target_moj_id",
              "document_references.target_moj_id",
              _m003_reference_target_moj_id),
    Migration("004_moj_id_index",
              "Bảng moj_id_index thay file cache moj_target_ids.json",
              _m004_moj_id_index),
    Migration("005_legal_facts",
              "Thứ bậc, phạm vi lãnh thổ, cờ hiệu lực chuẩn hoá",
              _m005_legal_facts),
    Migration("006_upload_queue",
              "Hàng đợi upload để thử lại khi đẩy lên mây thất bại",
              _m006_upload_queue),
    Migration("007_seed_cloud_synced_at",
              "Chuyển dấu vết upload Lark cũ sang cột cloud_synced_at",
              _m007_seed_cloud_synced_at),
    Migration("008_crawl_state",
              "Watermark bền vững và hàng đợi bao đóng dẫn chiếu",
              _m008_crawl_state),
    Migration("009_industry_impact",
              "Điểm tác động 21 ngành VSIC và hồ sơ ngành đã hiệu chuẩn",
              _m009_industry_impact),
    Migration("010_report_jobs",
              "Hàng đợi sinh báo cáo với cơ chế gộp chống ngập",
              _m010_report_jobs),
    Migration("011_tvpl_field",
              "Lĩnh vực theo danh mục TVPL (27 nhóm) kèm nguồn phân loại",
              _m011_tvpl_field),
    Migration("012_slug_chu_thuong",
              "Hạ chữ thường public_slug để khớp đường dẫn Quartz phát ra",
              _m012_slug_chu_thuong),
]


# ──────────────────────────────────────────────
# Bộ chạy
# ──────────────────────────────────────────────
def _ensure_history_table(conn: Connection) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id          TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """))


def applied_ids(conn: Connection) -> set[str]:
    _ensure_history_table(conn)
    return {row[0] for row in conn.execute(text("SELECT id FROM schema_migrations"))}


def run_migrations(conn: Connection) -> list[str]:
    """Chạy các migration chưa áp dụng, theo thứ tự. Trả về id đã chạy lần này.

    Mỗi bước commit riêng: một bước hỏng thì các bước trước vẫn giữ nguyên và
    lần chạy sau tiếp tục đúng chỗ dừng, thay vì cuộn lại toàn bộ.
    """
    done = applied_ids(conn)
    ran: list[str] = []

    for mig in MIGRATIONS:
        if mig.id in done:
            continue
        try:
            mig.run(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (id) VALUES (:i)"), {"i": mig.id}
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Migration %s thất bại — dừng tại đây", mig.id)
            raise
        ran.append(mig.id)
        logger.info("Migration %s xong: %s", mig.id, mig.description)

    return ran
