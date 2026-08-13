import math
import re
import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from src.legal.effectivity import HET_TOAN_BO
from src.rag.db_rag import RAGDatabase, HAS_VEC

@dataclass
class SearchResult:
    id: int
    doc_num: str
    # Định danh thật của văn bản. Thiếu nó thì bộ thẩm định hiệu lực ở cuối
    # đường chỉ có số hiệu trong tay và không phân biệt nổi hai tỉnh.
    doc_key: Optional[str]
    heading: str
    content: str
    final_score: float
    rrf_score: float
    fts_rank: Optional[int]
    vec_rank: Optional[int]
    usage_count: int
    days_old: float

def classify_query(query: str) -> str:
    q = query.strip()
    words = re.split(r'\s+', q)
    if len(words) == 1:
        return "KEYWORD"
    if re.search(r'[{}\(\)\[\];=<>]', q):
        return "KEYWORD"
    if re.search(r'\.\w{2,4}$', q) or re.search(r'[/\\]', q):
        return "KEYWORD"
    if q.endswith('?'):
        return "HYBRID"
    if re.match(r'^(what|how|why|when|where|who|which|cách|tại sao|làm sao|ở đâu|khi nào|thế nào)', q, re.IGNORECASE):
        return "HYBRID"
    return "HYBRID"

def rrf_fusion(fts_results: List[Dict], vec_results: List[Dict], k: int = 60) -> List[Dict]:
    scores = {}
    
    for idx, r in enumerate(fts_results):
        rid = r["id"]
        scores[rid] = {
            "rrf": 1 / (k + idx + 1),
            "fts_rank": idx + 1,
            "vec_rank": None
        }
        
    for idx, r in enumerate(vec_results):
        rid = r["id"]
        if rid not in scores:
            scores[rid] = {
                "rrf": 0,
                "fts_rank": None,
                "vec_rank": None
            }
        scores[rid]["rrf"] += 1 / (k + idx + 1)
        scores[rid]["vec_rank"] = idx + 1
        
    merged = [{"id": k, **v} for k, v in scores.items()]
    merged.sort(key=lambda x: x["rrf"], reverse=True)
    return merged

RECENCY_DECAY = 0.023 # 30-day half-life

def compute_final_score(rrf_score: float, days_old: float, usage_count: int, max_usage: int) -> float:
    relevance = min(1.0, rrf_score / 0.033)
    recency = math.exp(-RECENCY_DECAY * max(0, days_old))
    frequency = (usage_count / max_usage) if max_usage > 0 else 0
    return 0.5 * relevance + 0.3 * recency + 0.2 * frequency

# Mặc định mọi truy xuất đều loại văn bản đã hết hiệu lực toàn bộ và văn bản
# chỉ vào kho vì bị dẫn chiếu.
#
# Mặc định phải là AN TOÀN chứ không phải "lấy tất": trước đây bộ lọc chỉ chạy
# sau khi đã lấy 100 kết quả về, nên chỉ cần kho có nhiều văn bản chết là 100 chỗ
# đó bị chiếm sạch và báo cáo còn vài điều khoản — mà vẫn ra báo cáo, không có
# dấu hiệu nào cho thấy đã mất dữ liệu. Bao đóng dẫn chiếu biến tình huống đó
# thành mặc định.
#
# Muốn tra cứu cả văn bản lịch sử thì truyền filters={"exclude_eff_states": []}
# một cách có ý thức.
DEFAULT_FILTERS: Dict[str, Any] = {
    "exclude_eff_states": [HET_TOAN_BO],
    "exclude_closure": True,
}


def with_default_filters(filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ghép bộ lọc người gọi truyền vào lên trên bộ mặc định an toàn."""
    merged = dict(DEFAULT_FILTERS)
    if filters:
        merged.update(filters)
    return merged


def hybrid_search(
    db: RAGDatabase,
    query: str,
    embedder=None,
    limit: int = 10,
    filters: Optional[Dict[str, Any]] = None
) -> List[SearchResult]:
    if not query.strip():
        return []
        
    strategy = classify_query(query)
    filters = with_default_filters(filters)

    fts_results = db.search_fts(query, 100, filters=filters)
    vec_results = []

    if strategy == "HYBRID" and HAS_VEC and embedder:
        try:
            query_embedding = embedder.embed_single(query)
            if query_embedding:
                vec_results = db.search_vector(query_embedding, 100, filters=filters)
        except Exception as e:
            pass
            
    if not vec_results:
        merged = [
            {"id": r["id"], "rrf": 1 / (60 + idx + 1), "fts_rank": idx + 1, "vec_rank": None}
            for idx, r in enumerate(fts_results)
        ]
    elif not fts_results:
        merged = [
            {"id": r["id"], "rrf": 1 / (60 + idx + 1), "fts_rank": None, "vec_rank": idx + 1}
            for idx, r in enumerate(vec_results)
        ]
    else:
        merged = rrf_fusion(fts_results, vec_results)
        
    max_usage = db.get_max_usage_count()
    results = []
    
    for m in merged:
        doc = db.get_chunk(m["id"])
        if not doc:
            continue
            
        # Apply filters
        if filters:
            if filters.get("eff_status") and doc["eff_status"] != filters["eff_status"]:
                continue
            if filters.get("field_name") and doc["field_name"] != filters["field_name"]:
                continue
            if filters.get("industries"):
                import json
                # doc["industries"] có thể là NULL → .get(...,"[]") vẫn trả None
                # (khoá tồn tại), json.loads(None) ném TypeError. Trước đây bị
                # `except: pass` nuốt, nên chunk chưa phân ngành LỌT qua bộ lọc.
                raw = doc.get("industries") or "[]"
                try:
                    inds = json.loads(raw)
                except (TypeError, ValueError):
                    inds = []
                if filters["industries"] not in inds:
                    continue
            if filters.get("date_range") and doc.get("issue_date"):
                # Basic string compare for simplicity 'YYYY-MM-DD'
                dr = filters["date_range"]
                if not (isinstance(dr, (list, tuple)) and len(dr) == 2):
                    continue
                start_date, end_date = dr
                if doc["issue_date"] < start_date or doc["issue_date"] > end_date:
                    continue
            
        # Recency tính theo NGÀY BAN HÀNH của văn bản (tuổi thật của luật), KHÔNG
        # theo updated_at. updated_at là mốc REINDEX: sau mỗi lần nạp lại toàn kho
        # nó ≈ now cho mọi chunk, nên recency thành hằng số và số hạng recency
        # (trọng số 0.3) mất hẳn tác dụng — một luật 2015 nhìn "mới" ngang một nghị
        # định 2026, đúng ngược với nhu cầu của báo cáo cập nhật. issue_date dạng
        # 'YYYY-MM-DD'; so bằng date để tránh lệch múi giờ UTC/local.
        days_old = 0
        issue = doc.get("issue_date")
        if issue:
            try:
                ban_hanh = datetime.date.fromisoformat(str(issue)[:10])
                days_old = max(0, (datetime.date.today() - ban_hanh).days)
            except (ValueError, TypeError):
                pass
                
        final_score = compute_final_score(m["rrf"], days_old, doc.get("usage_count", 0), max_usage)
        
        results.append(SearchResult(
            id=m["id"],
            doc_num=doc["doc_num"],
            doc_key=doc.get("doc_key"),
            heading=doc["heading"],
            content=doc["content"],
            final_score=final_score,
            rrf_score=m["rrf"],
            fts_rank=m["fts_rank"],
            vec_rank=m["vec_rank"],
            usage_count=doc.get("usage_count", 0),
            days_old=days_old
        ))
        
    results.sort(key=lambda x: x.final_score, reverse=True)
    return results[:limit]


def industry_search(
    db: RAGDatabase,
    industry: str,
    limit: int = 60,
    embedder=None,
    per_query_limit: int = 35,
) -> List[SearchResult]:
    """Truy xuất theo NGÀNH bằng cả bộ từ khoá, không chỉ mỗi tên ngành.

    Tìm bằng đúng chuỗi tên ngành là cách tệ nhất: FTS5 yêu cầu MỌI token cùng
    xuất hiện trong một đoạn, nên "Y tế & Dược phẩm" trả về 0 kết quả và báo cáo
    ngành đó được sinh ra từ ngữ cảnh rỗng. INDUSTRY_MAP đã có sẵn bộ từ khoá
    chuyên ngành — mỗi từ khoá là một hướng truy vấn riêng, kết quả hợp nhất lại.

    Cách này cũng đáp ứng một phần yêu cầu "truy vấn tối thiểu 4 hướng" ở Bước 1
    của prompt báo cáo.
    """
    from src.obsidian.config_obsidian import INDUSTRY_MAP

    keywords = INDUSTRY_MAP.get(industry)
    if keywords is None:
        # Người dùng gõ tên ngành hơi khác với key trong map — khớp lỏng trước
        # khi chịu thua và dùng nguyên chuỗi.
        lowered = industry.strip().lower()
        for name, kws in INDUSTRY_MAP.items():
            if name.lower() == lowered or lowered in name.lower() or name.lower() in lowered:
                keywords = kws
                break

    queries: List[str] = [industry]
    if keywords:
        queries.extend(keywords)

    best: Dict[int, SearchResult] = {}
    for q in queries:
        for r in hybrid_search(db, query=q, limit=per_query_limit, embedder=embedder):
            prev = best.get(r.id)
            if prev is None or r.final_score > prev.final_score:
                best[r.id] = r

    merged = sorted(best.values(), key=lambda x: x.final_score, reverse=True)
    return merged[:limit]
