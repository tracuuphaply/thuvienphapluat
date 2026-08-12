"""
Dựng sẵn bản tóm tắt insight cho từng văn bản trong kho (bước ĐỌC).

Vì sao có script này. Báo cáo giờ được tổng hợp từ insight của từng văn bản
(xem src/rag/reports/summarizer.py) thay vì từ metadata. Nếu để việc tóm tắt xảy
ra ngay lúc sinh báo cáo, báo cáo ngành đầu tiên phải chờ ~22 lượt gọi mô hình
nối tiếp. Chạy script này sau mỗi lần cào để làm ấm cache trước: tới lúc sinh báo
cáo, phần lớn văn bản đã có sẵn insight và báo cáo ra gần như tức thì.

Idempotent: văn bản đã có insight đúng phiên bản và nội dung không đổi sẽ được bỏ
qua, không gọi lại mô hình. Một văn bản tóm tắt hỏng không chặn các văn bản sau.

Chạy:
    python -m scripts.backfill_document_insights --dry-run
    python -m scripts.backfill_document_insights --limit 50
    python -m scripts.backfill_document_insights --industry K
    python -m scripts.backfill_document_insights --force        # tóm tắt lại tất cả
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import text

from src.rag.db_rag import RAGDatabase
from src.rag.reports import summarizer
from src.rag.reports.llm import LLMUnavailable
from src.storage.database import get_session
from src.storage.models import Document

logger = logging.getLogger(__name__)


def _docs_co_chunk(session, industry: str | None, limit: int | None) -> list[Document]:
    """Văn bản đã tách đoạn — điều kiện cần để đọc sâu được.

    Lọc theo has_chunks thay vì thử từng văn bản rồi mới biết rỗng: đỡ một lượt
    truy vấn rag.db cho mỗi văn bản chỉ có metadata.
    """
    q = session.query(Document).filter(Document.has_chunks.is_(True))
    if industry:
        # industries là chuỗi tự do; khớp lỏng để không bỏ sót cách ghi khác nhau.
        q = q.filter(Document.industries.ilike(f"%{industry}%"))
    q = q.order_by(Document.issue_date.desc().nullslast())
    if limit:
        q = q.limit(limit)
    return q.all()


def run(industry: str | None, limit: int | None, force: bool, dry_run: bool) -> int:
    rag = RAGDatabase()
    stats = {"tom_tat": 0, "cache": 0, "khong_toan_van": 0, "loi": 0}

    with get_session() as session:
        docs = _docs_co_chunk(session, industry, limit)
        logger.info("Có %d văn bản cần dựng insight%s", len(docs),
                    f" (ngành {industry})" if industry else "")

        for doc in docs:
            doc_key = doc.doc_key or doc.doc_num
            if dry_run:
                cached = rag.get_document_insight(doc_key)
                da_co = bool(
                    cached
                    and cached.get("prompt_version") == summarizer.INSIGHT_PROMPT_VERSION
                    and not force
                )
                logger.info("  %s %s", "CACHE" if da_co else "SẼ TÓM TẮT", doc.doc_num)
                continue

            # Phân biệt cache-hit với tóm tắt mới để báo cáo cho người vận hành
            # biết mỗi lần chạy thực sự gọi mô hình bao nhiêu lượt.
            before = rag.get_document_insight(doc_key)
            was_valid = bool(
                before
                and before.get("prompt_version") == summarizer.INSIGHT_PROMPT_VERSION
            )
            try:
                insight = summarizer.insight_for_document(
                    rag, doc_key, doc.doc_num, doc.title or "", force=force
                )
            except (LLMUnavailable, ValueError, KeyError) as e:
                logger.warning("  LỖI %s: %s", doc.doc_num, e)
                stats["loi"] += 1
                continue

            if insight is None:
                stats["khong_toan_van"] += 1
            elif was_valid and not force:
                stats["cache"] += 1
            else:
                stats["tom_tat"] += 1

    logger.info(
        "Xong. Tóm tắt mới: %d · dùng cache: %d · không có toàn văn: %d · lỗi: %d",
        stats["tom_tat"], stats["cache"], stats["khong_toan_van"], stats["loi"],
    )
    return 0 if stats["loi"] == 0 else 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--industry", help="Lọc theo nhãn ngành trong cột industries")
    ap.add_argument("--limit", type=int, help="Chỉ xử lý N văn bản mới nhất")
    ap.add_argument("--force", action="store_true",
                    help="Tóm tắt lại kể cả khi cache còn hợp lệ")
    ap.add_argument("--dry-run", action="store_true",
                    help="Chỉ liệt kê văn bản nào sẽ tóm tắt, không gọi mô hình")
    args = ap.parse_args()
    return run(args.industry, args.limit, args.force, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
