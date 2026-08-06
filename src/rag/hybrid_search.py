import math
import re
import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from src.rag.db_rag import RAGDatabase, HAS_VEC

@dataclass
class SearchResult:
    id: int
    doc_num: str
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
    
    fts_results = db.search_fts(query, 100)
    vec_results = []
    
    if strategy == "HYBRID" and HAS_VEC and embedder:
        try:
            query_embedding = embedder.embed_single(query)
            if query_embedding:
                vec_results = db.search_vector(query_embedding, 100)
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
                try:
                    inds = json.loads(doc.get("industries", "[]"))
                    if filters["industries"] not in inds:
                        continue
                except:
                    pass
            if filters.get("date_range") and doc.get("issue_date"):
                # Basic string compare for simplicity 'YYYY-MM-DD'
                start_date, end_date = filters["date_range"]
                if doc["issue_date"] < start_date or doc["issue_date"] > end_date:
                    continue
            
        days_old = 0
        if doc.get("updated_at"):
            try:
                # SQLite datetime format is usually 'YYYY-MM-DD HH:MM:SS'
                date_str = doc["updated_at"].replace(" ", "T")
                if not date_str.endswith("Z"):
                     # Simple parsing
                     updated_date = datetime.datetime.fromisoformat(date_str)
                     days_old = (datetime.datetime.now() - updated_date).days
            except:
                pass
                
        final_score = compute_final_score(m["rrf"], days_old, doc.get("usage_count", 0), max_usage)
        
        results.append(SearchResult(
            id=m["id"],
            doc_num=doc["doc_num"],
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
