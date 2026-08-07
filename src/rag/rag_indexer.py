import json
import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Any
from src.config import DATA_DIR
from src.storage.database import get_session
from src.storage.models import Document, DocumentReference
from src.rag.db_rag import RAGDatabase, HAS_VEC
from src.rag.embeddings_api import EmbeddingAPI
from src.obsidian.industry_classifier import classify_industries

logger = logging.getLogger(__name__)

def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _embed_pending(rag_db: RAGDatabase, embedder, pending: list[tuple[int, str]],
                   batch_size: int = 100) -> int:
    """Nhúng theo lô rồi ghi vector, commit mỗi lô thay vì mỗi chunk."""
    total = len(pending)
    written = 0
    logger.info("Bắt đầu nhúng %d đoạn...", total)

    for start in range(0, total, batch_size):
        window = pending[start:start + batch_size]
        vectors = embedder.embed_texts([text for _, text in window])
        for (chunk_id, _), vector in zip(window, vectors):
            if not vector:
                continue
            try:
                rag_db.upsert_vector(chunk_id, vector, commit=False)
                written += 1
            except ValueError as e:
                # Lệch số chiều là lỗi cấu hình, không phải lỗi dữ liệu — dừng
                # hẳn thay vì ghi hỏng cả bảng.
                rag_db.db.rollback()
                raise RuntimeError(f"Nhúng thất bại ở chunk {chunk_id}: {e}") from e
        rag_db.db.commit()
        logger.info("  đã nhúng %d/%d", min(start + batch_size, total), total)

    logger.info("Nhúng xong: %d/%d đoạn có vector.", written, total)
    return written

def embed_missing(rag_db: RAGDatabase, embedder=None, batch_size: int = 100) -> int:
    """Nhúng những đoạn còn thiếu vector, bỏ qua đoạn đã có.

    Nhúng cả kho mất hàng chục phút; nếu tiến trình đứt giữa chừng thì chạy lại
    từ đầu vừa tốn tiền vừa tốn thời gian. Hàm này chỉ làm phần còn thiếu, nên
    an toàn khi gọi lại nhiều lần.
    """
    if not HAS_VEC:
        logger.warning("Chưa cài sqlite-vec — bỏ qua bước nhúng.")
        return 0

    embedder = embedder or EmbeddingAPI()
    if not embedder.api_key:
        logger.warning("Chưa cấu hình khoá API nhúng — bỏ qua bước nhúng.")
        return 0

    rows = rag_db.db.execute("""
        SELECT c.id, c.doc_num, c.heading, c.content
        FROM legal_chunks c
        WHERE c.id NOT IN (SELECT rowid FROM legal_chunks_vec)
        ORDER BY c.id
    """).fetchall()
    if not rows:
        logger.info("Mọi đoạn đều đã có vector.")
        return 0

    pending = [
        (r["id"], embedder.prepare_legal_text(r["content"], r["doc_num"], r["heading"]))
        for r in rows
    ]
    logger.info("Còn %d đoạn chưa có vector.", len(pending))
    return _embed_pending(rag_db, embedder, pending, batch_size=batch_size)



# Trường của bảng documents mà tầng RAG cần: metadata hiển thị + cột lọc.
_META_FIELDS = (
    "doc_num", "title", "field_name", "field_code", "industries",
    "eff_status", "issue_date", "doc_type", "agency_name", "tvpl_id",
    "eff_state", "is_closure_node", "hierarchy_level", "is_vbqppl",
)


def load_document_metadata() -> dict[str, dict]:
    """Metadata cho tầng RAG, đọc thẳng từ bảng documents.

    Trước đây hàm này đọc data/metadata/*.json. Các file đó là bản sao được ghi
    lúc cào và không cập nhật lại, nên mọi trường tính về sau — cờ hiệu lực
    chuẩn hoá, cấp hiệu lực, cờ văn bản ngữ cảnh — đều rỗng trong RAG index dù
    cơ sở dữ liệu đã có đủ. Đúng loại lỗi từng khiến vault render link nguồn
    rỗng trên cả 1015 note.

    Khoá theo doc_num vì legal_chunks cũng khoá theo doc_num. Số hiệu trùng giữa
    các tỉnh thì bản ghi sau ghi đè bản trước — hạn chế đã biết của tầng chunk,
    sẽ hết khi chunk chuyển sang doc_key.
    """
    from src.storage.database import get_session
    from src.storage.models import Document

    out: dict[str, dict] = {}
    with get_session() as session:
        for doc in session.query(Document).all():
            out[doc.doc_num] = {f: getattr(doc, f, None) for f in _META_FIELDS}
    return out


def index_from_phase1(db_path: Path, rag_db: RAGDatabase, force: bool = False, stats_only: bool = False):
    chunks_dir = DATA_DIR / "chunks"
    meta_dir = DATA_DIR / "metadata"
    
    if stats_only:
        cursor = rag_db.db.execute("SELECT COUNT(*) FROM legal_chunks")
        chunks_count = cursor.fetchone()[0]
        cursor = rag_db.db.execute("SELECT COUNT(*) FROM legal_graph")
        graph_count = cursor.fetchone()[0]
        logger.info(f"RAG DB Stats: {chunks_count} chunks, {graph_count} graph edges.")
        print(f"RAG DB Stats: {chunks_count} chunks, {graph_count} graph edges.")
        
        if HAS_VEC:
            cursor = rag_db.db.execute("SELECT COUNT(*) FROM legal_chunks_vec")
            vec_count = cursor.fetchone()[0]
            logger.info(f"Vector Count: {vec_count}")
            print(f"Vector Count: {vec_count}")
        else:
            print("Vector Search is not available (sqlite-vec not installed).")
        return

    embedder = EmbeddingAPI()
    
    # Process chunks and metadata
    chunk_files = list(chunks_dir.glob("*_chunks.json"))
    logger.info(f"Found {len(chunk_files)} chunk files.")
    
    meta_by_doc_num = load_document_metadata()
    logger.info(f"Đã nạp metadata cho {len(meta_by_doc_num)} văn bản.")

    pending_embeddings: list[tuple[int, str]] = []

    for cfile in chunk_files:
        try:
            with open(cfile, 'r', encoding='utf-8') as f:
                chunks = json.load(f)

            if not chunks:
                continue

            file_doc_num = next(
                (c.get("doc_num") for c in chunks if c.get("doc_num")), None
            )
            meta_data = meta_by_doc_num.get(file_doc_num, {}) if file_doc_num else {}
            if file_doc_num and not meta_data:
                logger.warning(f"Không tìm thấy metadata cho {file_doc_num}")

            for chunk in chunks:
                content = chunk.get("content", "")
                chash = hash_content(content)
                doc_num = chunk.get("doc_num", meta_data.get("doc_num"))
                c_idx = chunk.get("chunk_index", 0)

                # Check existing
                cursor = rag_db.db.execute("SELECT id, content_hash FROM legal_chunks WHERE doc_num = ? AND chunk_index = ?", (doc_num, c_idx))
                existing = cursor.fetchone()

                # Nội dung không đổi thì không cần nhúng lại, nhưng metadata vẫn
                # phải được làm mới: trạng thái hiệu lực đổi mà điều khoản giữ
                # nguyên là trường hợp phổ biến nhất.
                content_unchanged = bool(existing) and existing["content_hash"] == chash

                chunk_data = {
                    "doc_id": chunk.get("doc_id", meta_data.get("tvpl_id")),
                    "doc_num": doc_num,
                    "chunk_index": c_idx,
                    "heading": chunk.get("heading", ""),
                    "content": content,
                    "char_count": chunk.get("char_count", len(content)),
                    "field_name": meta_data.get("field_name"),
                    "field_code": meta_data.get("field_code"),
                    # metadata/*.json để industries rỗng cho toàn bộ 314 văn bản
                    # (bộ phân loại chỉ chạy lúc xuất vault), nên filter theo
                    # ngành ở tầng RAG không bao giờ khớp. Tính tại chỗ khi thiếu.
                    "industries": meta_data.get("industries") or classify_industries(
                        meta_data.get("title", ""),
                        meta_data.get("field_name"),
                        content,
                    ),
                    "eff_status": meta_data.get("eff_status"),
                    "issue_date": meta_data.get("issue_date"),
                    "doc_type": meta_data.get("doc_type"),
                    "agency_name": meta_data.get("agency_name"),
                    # Cột lọc — phải có ở tầng chunk để điều kiện đi vào
                    # câu SQL. Thiếu chúng thì bộ lọc chỉ chạy sau khi đã
                    # lấy 100 kết quả về, và văn bản đã hết hiệu lực chiếm
                    # sạch chỗ ngay khi kho lớn lên vì bao đóng dẫn chiếu.
                    "eff_state": meta_data.get("eff_state"),
                    "is_closure_node": meta_data.get("is_closure_node"),
                    "hierarchy_level": meta_data.get("hierarchy_level"),
                    "is_vbqppl": meta_data.get("is_vbqppl"),
                    "content_hash": chash
                }
                
                chunk_id = rag_db.upsert_chunk(chunk_data, commit=False)

                if content_unchanged and not force:
                    continue

                if HAS_VEC and embedder.api_key:
                    # Gom lại để nhúng theo lô: embed_single gọi 1 HTTP request
                    # mỗi chunk, tức 6124 request thay vì 613.
                    pending_embeddings.append((
                        chunk_id,
                        embedder.prepare_legal_text(
                            content, chunk_data["doc_num"], chunk_data["heading"]
                        ),
                    ))

            rag_db.db.commit()

        except Exception as e:
            rag_db.db.rollback()
            logger.error(f"Error processing {cfile}: {e}")

    if pending_embeddings:
        _embed_pending(rag_db, embedder, pending_embeddings)

    logger.info("Indexing graph edges from Phase 1 DB...")
    try:
        with get_session() as session:
            # Phân giải đích qua target_doc_id (khoá ngoại thật) chứ không qua
            # số hiệu: đó là điểm khiến hai văn bản trùng số hiệu không còn bị
            # gộp thành một cạnh.
            key_by_id = {d.id: d.doc_key for d in session.query(Document).all()}
            edges = session.query(DocumentReference).all()
            for edge in edges:
                src = edge.source_doc
                if not (src and src.doc_num and src.doc_key):
                    continue
                rag_db.upsert_graph_edge(
                    source_doc_key=src.doc_key,
                    source_doc_num=src.doc_num,
                    target_doc_key=key_by_id.get(edge.target_doc_id),
                    target_doc_num=edge.target_doc_num,
                    relation_type=edge.relation_type,
                    commit=False,
                )
            rag_db.db.commit()
    except Exception as e:
        logger.error(f"Error indexing graph edges: {e}")

    logger.info("Indexing complete.")
