from typing import List, Dict, Any, Optional
from collections import deque
from src.rag.db_rag import RAGDatabase

class GraphEdge:
    def __init__(self, source: str, target: str, relation: str, confidence: float):
        self.source = source
        self.target = target
        self.relation = relation
        self.confidence = confidence

class AffectedDoc:
    def __init__(self, doc_num: str, relation: str, doc_key: Optional[str] = None):
        self.doc_num = doc_num
        self.relation = relation
        # Rỗng khi văn bản đầu kia chưa có trong kho — cạnh treo vẫn phải hiện,
        # vì "có một văn bản sửa đổi mà ta chưa tải về" là thông tin, không phải
        # thứ để giấu đi.
        self.doc_key = doc_key

def cascade_retrieve(db: RAGDatabase, doc_num: str, max_depth: int = 2) -> List[GraphEdge]:
    visited = set([doc_num])
    queue = deque([(doc_num, 0)])
    edges = []
    
    while queue:
        current_doc, depth = queue.popleft()
        if depth >= max_depth:
            continue
            
        cursor = db.db.execute("SELECT * FROM legal_graph WHERE source_doc_num = ? OR target_doc_num = ?", (current_doc, current_doc))
        for row in cursor.fetchall():
            src = row['source_doc_num']
            tgt = row['target_doc_num']
            rel = row['relation_type']
            conf = row['confidence']
            
            edges.append(GraphEdge(src, tgt, rel, conf))
            
            next_doc = tgt if src == current_doc else src
            if next_doc not in visited:
                visited.add(next_doc)
                queue.append((next_doc, depth + 1))
                
    unique_edges = {}
    for e in edges:
        unique_edges[(e.source, e.target, e.relation)] = e
    return list(unique_edges.values())

# Quan hệ làm văn bản ĐÍCH mất hiệu lực — không được trích dẫn như luật hiện hành.
TERMINATING_RELATIONS = ("Bãi bỏ", "Hủy bỏ", "Thay thế", "Đình chỉ")

# Quan hệ chỉ sửa nội dung: văn bản đích VẪN còn hiệu lực ở phần chưa bị sửa,
# nên phải giữ lại và cảnh báo, không được loại bỏ như bản đã chết.
AMENDING_RELATIONS = ("Sửa đổi, bổ sung",)


def impact_analysis(
    db: RAGDatabase, doc_num: str, doc_key: Optional[str] = None
) -> List[AffectedDoc]:
    """Các văn bản chịu tác động, theo cả hai chiều.

    Chiều xuôi: văn bản này tác động lên ai.
    Chiều ngược: ai đang tác động lên văn bản này — đây mới là câu hỏi quan
    trọng khi thẩm định hiệu lực, và bản cũ hoàn toàn không trả lời được.

    Vẫn nhận số hiệu vì đó là thứ người dùng gõ và thứ mô hình sinh ra. Truyền
    thêm `doc_key` khi đã biết chính xác văn bản nào — ví dụ "64/2026/QĐ-UBND"
    của Huế chứ không phải của Tây Ninh; thiếu nó thì kết quả là hợp của mọi văn
    bản trùng số hiệu.
    """
    xuoi = db.db.execute(
        "SELECT target_doc_num, target_doc_key, relation_type FROM legal_graph "
        "WHERE source_doc_num = ?" + (" AND source_doc_key = ?" if doc_key else ""),
        (doc_num, doc_key) if doc_key else (doc_num,),
    ).fetchall()

    nguoc = db.db.execute(
        "SELECT source_doc_num, source_doc_key, relation_type FROM legal_graph "
        "WHERE target_doc_num = ?" + (" AND target_doc_key = ?" if doc_key else ""),
        (doc_num, doc_key) if doc_key else (doc_num,),
    ).fetchall()

    # Không gộp theo số hiệu: hai văn bản trùng số hiệu là hai văn bản thật,
    # gộp lại là làm biến mất một cái. Ràng buộc UNIQUE của bảng đã bảo đảm
    # không có dòng nào lặp, nên ở đây không cần khử trùng.
    out = [AffectedDoc(r[0], r[2], r[1]) for r in xuoi]
    out += [AffectedDoc(r[0], f"bị {r[2].lower()} bởi", r[1]) for r in nguoc]
    return out


def _ke_tac_dong(
    db: RAGDatabase, doc_num: str, relations: tuple, doc_key: Optional[str]
) -> List[tuple]:
    """Danh sách (số hiệu, quan hệ) — đã bỏ doc_key nên phải khử trùng.

    Hai Quyết định trùng số hiệu của hai tỉnh cùng bãi bỏ một văn bản là hai
    cạnh thật, nhưng chiếu xuống còn số hiệu thì ra hai dòng chữ y hệt nhau.
    Câu cảnh báo "bị sửa đổi bởi: 64/2026/QĐ-UBND, 64/2026/QĐ-UBND" chỉ làm
    người đọc tưởng hệ thống hỏng.
    """
    placeholders = ",".join("?" * len(relations))
    cursor = db.db.execute(
        f"""SELECT source_doc_num, relation_type FROM legal_graph
            WHERE target_doc_num = ? AND relation_type IN ({placeholders})"""
        + (" AND target_doc_key = ?" if doc_key else ""),
        (doc_num, *relations, doc_key) if doc_key else (doc_num, *relations),
    )
    seen, out = set(), []
    for r in cursor.fetchall():
        row = (r["source_doc_num"], r["relation_type"])
        if row not in seen:
            seen.add(row)
            out.append(row)
    return out


def effect_warnings(
    db: RAGDatabase, doc_num: str, doc_key: Optional[str] = None
) -> Dict[str, Any]:
    """Tra đồ thị xem văn bản có bị chấm dứt hoặc bị sửa đổi không."""
    return {
        "terminated_by": _ke_tac_dong(db, doc_num, TERMINATING_RELATIONS, doc_key),
        "amended_by": _ke_tac_dong(db, doc_num, AMENDING_RELATIONS, doc_key),
    }


# Trạng thái tự thân của văn bản, độc lập với đồ thị quan hệ. Nguồn Bộ Tư pháp
# ghi sẵn trạng thái này và nó chính xác hơn suy luận từ cạnh quan hệ.
EXPIRED_STATUSES = ("hết hiệu lực toàn bộ", "hết hiệu lực")
PARTIAL_STATUSES = ("hết hiệu lực một phần",)
NOT_YET_STATUSES = ("chưa có hiệu lực",)


def document_status(db: RAGDatabase, doc_num: str) -> str:
    """eff_status của văn bản, đọc từ metadata đã gắn vào chunk."""
    row = db.db.execute(
        "SELECT eff_status FROM legal_chunks WHERE doc_num = ? AND eff_status IS NOT NULL LIMIT 1",
        (doc_num,),
    ).fetchone()
    return (row["eff_status"] or "").strip() if row else ""


def validate_results(db: RAGDatabase, chunks: List[Dict]) -> List[Dict]:
    """Loại đoạn thuộc văn bản đã hết hiệu lực, gắn cảnh báo cho văn bản bị sửa đổi.

    Hai nguồn thông tin được dùng cùng lúc:
      - eff_status của chính văn bản (Bộ Tư pháp ghi sẵn)
      - quan hệ trong đồ thị (ai bãi bỏ / thay thế / sửa đổi văn bản này)

    Văn bản "Hết hiệu lực một phần" hoặc bị sửa đổi KHÔNG bị loại: phần chưa bị
    sửa vẫn là luật hiện hành. Loại nhầm nhóm này sẽ xoá mất 220/1015 văn bản.

    GIỚI HẠN CÒN LẠI. Hàm này tra theo số hiệu vì `legal_chunks` cũng khoá theo
    số hiệu — hai văn bản trùng số hiệu đang dùng chung một tập chunk, nên không
    có gì để phân biệt ở tầng này. Hệ quả: một văn bản tỉnh bị bãi bỏ sẽ kéo
    theo văn bản cùng số hiệu của tỉnh khác. Sai lệch này thiên về loại thừa,
    không phải trích dẫn nhầm luật đã chết, nên chấp nhận được cho tới khi
    `legal_chunks` cũng chuyển sang doc_key (phải index lại ~46.000 đoạn).
    """
    valid_chunks: List[Dict] = []
    for c in chunks:
        doc_num = c.get("doc_num")
        if not doc_num:
            valid_chunks.append(c)
            continue

        status = document_status(db, doc_num).lower()
        if status in EXPIRED_STATUSES:
            continue

        warn = effect_warnings(db, doc_num)
        if warn["terminated_by"]:
            continue

        notes: List[str] = []
        if status in PARTIAL_STATUSES:
            notes.append("Văn bản đã hết hiệu lực MỘT PHẦN — phải kiểm tra điều khoản trích dẫn còn hiệu lực không")
        if status in NOT_YET_STATUSES:
            notes.append("Văn bản CHƯA có hiệu lực tại thời điểm chốt dữ liệu")
        if warn["amended_by"]:
            notes.append("Đã bị sửa đổi, bổ sung bởi: " + ", ".join(
                src for src, _ in warn["amended_by"]
            ))

        if notes:
            c = dict(c)
            c["canh_bao_hieu_luc"] = " | ".join(notes)
        valid_chunks.append(c)

    return valid_chunks

def get_full_context(db: RAGDatabase, doc_num: str) -> Dict[str, Any]:
    """Get a doc + all related docs in one call."""
    context = {
        "primary_doc": doc_num,
        "chunks": [],
        "related_docs": []
    }
    
    cursor = db.db.execute("SELECT * FROM legal_chunks WHERE doc_num = ? ORDER BY chunk_index", (doc_num,))
    context["chunks"] = [dict(r) for r in cursor.fetchall()]
    
    edges = cascade_retrieve(db, doc_num, max_depth=1)
    related_set = set()
    for e in edges:
        if e.source != doc_num:
            related_set.add((e.source, e.relation))
        if e.target != doc_num:
            related_set.add((e.target, e.relation))
            
    for rel_doc, rel_type in related_set:
        context["related_docs"].append({
            "doc_num": rel_doc,
            "relation": rel_type
        })
        
    return context
