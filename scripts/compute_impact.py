"""
Chấm mức độ tác động của từng văn bản lên 21 ngành VSIC.

    python -m scripts.compute_impact --build-profiles   # một lần, cần khoá nhúng
    python -m scripts.compute_impact --dry-run
    python -m scripts.compute_impact

TÁI LẬP: cùng dữ liệu + cùng `scorer_version` luôn ra cùng con số. Hồ sơ ngành,
vector tâm và (mean, sd) hiệu chuẩn đều được đóng băng vào bảng `industry_profile`
chứ không tính lại mỗi lần — nhúng lại cùng một câu trên model đang trôi sẽ làm
điểm số đổi thầm lặng.
"""
from __future__ import annotations

import argparse
import json
import logging
import struct
from collections import Counter

from sqlalchemy import text

from src.analysis import centroids, scorer
from src.analysis.restrictions import count_restrictions
from src.config import impact_scorer_version
from src.obsidian.industry_classifier import score_industries
from src.obsidian.vsic import BY_CODE
from src.rag.db_rag import RAGDatabase
from src.storage.database import get_session, init_db

logger = logging.getLogger(__name__)


def version_tag() -> str:
    """Giữ lại làm bí danh; phần thực hiện đã chuyển vào src/config.py.

    Sáu chỗ từng import hàm này TỪ MỘT SCRIPT, trong đó có src/rag/reports/
    jobs.py — mã thư viện phụ thuộc vào thư mục script. Nay chúng gọi thẳng
    config; hàm này chỉ còn cho ai đang gõ dở lệnh cũ.
    """
    return impact_scorer_version()


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


# ──────────────────────────────────────────────
# Hồ sơ ngành
# ──────────────────────────────────────────────
def build_profiles(session, rag: RAGDatabase, version: str) -> int:
    """Dựng và đóng băng 21 hồ sơ ngành + tham số hiệu chuẩn.

    Ba việc trong một lượt vì chúng phụ thuộc nhau: vector hồ sơ cần embedding
    API, vector tâm cần toàn bộ vector kho, còn (mean, sd) cần cả hai.
    """
    from src.rag.embeddings_api import EmbeddingAPI

    embedder = EmbeddingAPI()
    if not embedder.api_key:
        raise RuntimeError("Chưa cấu hình khoá API nhúng — không dựng được hồ sơ ngành.")

    profiles = centroids.all_profiles()
    logger.info("Nhúng %d hồ sơ ngành...", len(profiles))

    # Vector tâm của toàn kho. Trừ tâm là bắt buộc: văn bản pháp luật tiếng Việt
    # nhúng ra cụm rất chặt nên cosine thô không phân biệt được ngành nào.
    chunk_vectors = _sample_corpus_vectors(rag, limit=4000)
    if not chunk_vectors:
        raise RuntimeError("Kho chưa có vector nào — chạy `src.main --sync-rag-only` trước.")
    corpus_mean = centroids.mean_vector(chunk_vectors)
    logger.info("Vector tâm dựng từ %d đoạn.", len(chunk_vectors))

    centered_corpus = [centroids.subtract(v, corpus_mean) for v in chunk_vectors]

    written = 0
    for profile in profiles:
        vectors = [v for v in embedder.embed_texts(list(profile.texts)) if v]
        if not vectors:
            logger.warning("Ngành %s: không nhúng được câu nào", profile.vsic_code)
            continue
        centroid = centroids.normalize(
            centroids.subtract(centroids.mean_vector(vectors), corpus_mean)
        )

        # Hiệu chuẩn: phân phối cosine của ngành này trên mẫu kho. Không có bước
        # này thì so cosine giữa các ngành là so hai thước đo khác đơn vị.
        sims = [centroids.cosine(v, centroid) for v in centered_corpus]
        mean = sum(sims) / len(sims)
        sd = (sum((s - mean) ** 2 for s in sims) / len(sims)) ** 0.5

        session.execute(text("""
            INSERT INTO industry_profile
                (vsic_code, scorer_version, embedding, corpus_mean, mean, sd, built_from)
            VALUES (:c, :v, :e, :m, :mean, :sd, :bf)
            ON CONFLICT(vsic_code, scorer_version) DO UPDATE SET
                embedding=excluded.embedding, corpus_mean=excluded.corpus_mean,
                mean=excluded.mean, sd=excluded.sd, built_from=excluded.built_from,
                built_at=datetime('now')
        """), {
            "c": profile.vsic_code, "v": version,
            "e": _pack(centroid), "m": _pack(corpus_mean),
            "mean": mean, "sd": sd,
            "bf": json.dumps(list(profile.texts), ensure_ascii=False),
        })
        written += 1
        logger.info("  %s %-40s mean=%.4f sd=%.4f",
                    profile.vsic_code, profile.name, mean, sd)

    return written


def _sample_corpus_vectors(rag: RAGDatabase, limit: int) -> list[list[float]]:
    """Mẫu vector đại diện cho kho, lấy trải đều theo id.

    Lấy mẫu chứ không lấy hết vì 43.000 vector × 1536 chiều là hơn 250 MB trong
    bộ nhớ, trong khi vector tâm hội tụ từ vài nghìn mẫu.
    """
    total = rag.db.execute("SELECT COUNT(*) FROM legal_chunks_vec").fetchone()[0]
    if not total:
        return []
    step = max(1, total // limit)
    rows = rag.db.execute(
        "SELECT embedding FROM legal_chunks_vec WHERE rowid % ? = 0 LIMIT ?",
        (step, limit),
    ).fetchall()
    return [_unpack(r[0]) for r in rows]


def load_profiles(session, version: str) -> dict[str, dict]:
    rows = session.execute(text(
        "SELECT vsic_code, embedding, corpus_mean, mean, sd "
        "FROM industry_profile WHERE scorer_version = :v"
    ), {"v": version}).mappings().all()
    return {
        r["vsic_code"]: {
            "centroid": _unpack(r["embedding"]),
            "corpus_mean": _unpack(r["corpus_mean"]),
            "mean": r["mean"], "sd": r["sd"],
        }
        for r in rows
    }


# ──────────────────────────────────────────────
# Chấm điểm
# ──────────────────────────────────────────────
def _lexicon_relevance(title: str, field_name: str, content: str) -> dict[str, float]:
    """Xác suất liên quan ngành theo từ khoá, chuẩn hoá thành phân phối."""
    by_name = score_industries(title, field_name, content)
    if not by_name:
        return {}
    name_to_code = {n["ten_ngan"]: c for c, n in BY_CODE.items()}
    raw = {name_to_code[n]: float(s) for n, s in by_name.items() if n in name_to_code}
    total = sum(raw.values())
    return {c: v / total for c, v in raw.items()} if total else {}


def _embedding_relevance(
    chunk_vectors: list[list[float]], profiles: dict[str, dict]
) -> dict[str, float]:
    """Xác suất liên quan ngành theo ngữ nghĩa.

    Lấy trung bình top-k đoạn cao điểm nhất chứ không trung bình toàn bộ: một
    đạo luật 300 Điều nhắc tới ngân hàng ở 5 Điều VẪN là văn bản ngân hàng, nhưng
    trung bình 300 đoạn pha loãng tín hiệu đó về 0.
    """
    if not chunk_vectors or not profiles:
        return {}

    corpus_mean = next(iter(profiles.values()))["corpus_mean"]
    centered = [centroids.subtract(v, corpus_mean) for v in chunk_vectors]

    raw: dict[str, float] = {}
    for code, p in profiles.items():
        zs = sorted(
            (centroids.zscore(centroids.cosine(v, p["centroid"]), p["mean"], p["sd"])
             for v in centered),
            reverse=True,
        )
        k = min(centroids.TOP_K_CHUNKS, len(zs))
        raw[code] = sum(zs[:k]) / k
    return centroids.softmax(raw)


def compute(session, rag: RAGDatabase, version: str, dry_run: bool) -> Counter:
    from src.storage.models import Document

    stats: Counter = Counter({
        "van_ban": 0, "co_diem": 0, "khong_co_rang_buoc": 0,
        "chi_tu_khoa": 0, "chi_ngu_nghia": 0, "ca_hai_tang": 0,
    })

    profiles = load_profiles(session, version)
    if not profiles:
        raise RuntimeError(
            f"Chưa có hồ sơ ngành cho {version}. Chạy: --build-profiles"
        )
    logger.info("Đã nạp %d hồ sơ ngành cho %s", len(profiles), version)

    impacts: list[scorer.DocumentImpact] = []
    docs = session.query(Document).order_by(Document.id).all()

    for doc in docs:
        stats["van_ban"] += 1
        # Theo doc_key, nếu không hai văn bản trùng số hiệu nhận CÙNG một điểm
        # tác động tính trên tập đoạn trộn lẫn của cả hai.
        rows = rag.db.execute("""
            SELECT c.content, v.embedding
            FROM legal_chunks c
            LEFT JOIN legal_chunks_vec v ON v.rowid = c.id
            WHERE COALESCE(c.doc_key, c.doc_num) = ?
        """, (doc.doc_key or doc.doc_num,)).fetchall()
        if not rows:
            continue

        restriction = sum(count_restrictions(r[0]).weighted for r in rows)
        if not restriction:
            stats["khong_co_rang_buoc"] += 1
            continue

        content = "\n".join(r[0] or "" for r in rows)
        lex = _lexicon_relevance(doc.title or "", doc.field_name or "", content)
        vectors = [_unpack(r[1]) for r in rows if r[1]]
        emb = _embedding_relevance(vectors, profiles)

        if lex and emb:
            stats["ca_hai_tang"] += 1
        elif lex:
            stats["chi_tu_khoa"] += 1
        elif emb:
            stats["chi_ngu_nghia"] += 1
        else:
            continue

        impacts.append(scorer.score_document(
            doc_key=doc.doc_key, doc_num=doc.doc_num,
            restriction_weighted=restriction,
            relevance_lexicon=lex, relevance_embedding=emb,
            hierarchy_level=doc.hierarchy_level,
        ))
        stats["co_diem"] += 1

    # Chấm xong hết rồi mới xếp hạng, vì phân vị cần cả phân phối.
    #
    # Nhóm tham chiếu là văn bản NGHIỆP VỤ, không gồm văn bản ngữ cảnh kéo về
    # theo dẫn chiếu. Văn bản ngữ cảnh vẫn được chấm và vẫn nhận phân vị — chúng
    # chỉ không được tham gia định nghĩa "cao" là bao nhiêu.
    nghiep_vu = {
        d.doc_key for d in docs if not d.is_closure_node and d.doc_key
    }
    logger.info(
        "Phân vị so trên %d văn bản nghiệp vụ (bỏ %d văn bản ngữ cảnh khỏi "
        "phân phối tham chiếu).", len(nghiep_vu), len(docs) - len(nghiep_vu),
    )
    scorer.assign_percentiles(impacts, reference_keys=nghiep_vu)

    if not dry_run:
        session.execute(
            text("DELETE FROM document_industry_impact WHERE scorer_version = :v"),
            {"v": version},
        )
        for impact in impacts:
            for score in impact.scores.values():
                session.execute(text("""
                    INSERT INTO document_industry_impact
                        (doc_key, doc_num, vsic_code, scorer_version,
                         restriction_weighted, relevance_lexicon, relevance_embedding,
                         relevance_fused, impact_raw, impact_pct_doc, impact_pct_industry)
                    VALUES (:k, :n, :c, :v, :rw, :rl, :re, :rf, :ir, :pd, :pi)
                """), {
                    "k": impact.doc_key, "n": impact.doc_num, "c": score.vsic_code,
                    "v": version, "rw": impact.restriction_weighted,
                    "rl": score.relevance_lexicon, "re": score.relevance_embedding,
                    "rf": score.relevance_fused, "ir": score.impact_raw,
                    "pd": score.impact_pct_doc, "pi": score.impact_pct_industry,
                })
        session.commit()

    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build-profiles", action="store_true",
                    help="Dựng lại 21 hồ sơ ngành (cần khoá API nhúng)")
    ap.add_argument("--dry-run", action="store_true", help="Chấm nhưng không ghi")
    args = ap.parse_args()

    init_db()
    version = version_tag()
    print(f"scorer_version = {version}\n")

    rag = RAGDatabase()
    try:
        with get_session() as session:
            if args.build_profiles:
                n = build_profiles(session, rag, version)
                session.commit()
                print(f"Đã dựng {n} hồ sơ ngành.\n")

            stats = compute(session, rag, version, args.dry_run)
    finally:
        rag.close()

    print("=== Kết quả ===" + ("  (DRY RUN)" if args.dry_run else ""))
    for k in sorted(stats):
        print(f"  {k:24} {stats[k]:>6}")


if __name__ == "__main__":
    main()
