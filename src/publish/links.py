"""
Chèn link từ báo cáo về trang tra cứu công khai.

LINK DO CODE CHÈN, KHÔNG ĐỂ MÔ HÌNH VIẾT. Mục 7 của prompt cấm mô hình viết liên
kết, và đó là quyết định đúng: URL do mô hình sinh là URL bịa, y hệt số hiệu do
mô hình sinh. Ở đây ta tra `documents.public_slug` rồi tự dựng địa chỉ, nên URL
bịa là bất khả thi về mặt cấu trúc.

CHỈ PHÁT LINK KHI TRANG ĐÃ THỰC SỰ CÔNG KHAI. Cột `published_hash` chỉ có giá
trị sau khi trang được ghi ra thư mục publish. Một báo cáo trỏ tới 404 tệ hơn
một báo cáo không có link — nó khiến người đọc nghi ngờ cả những phần đúng.
"""
from __future__ import annotations

import logging

from src.config import PUBLIC_VAULT_BASE_URL
from src.rag.citation_check import extract_doc_nums
from src.storage.models import Document

logger = logging.getLogger(__name__)


def public_url(slug: str) -> str:
    base = (PUBLIC_VAULT_BASE_URL or "").rstrip("/")
    return f"{base}/van-ban/{slug}" if base and slug else ""


def resolve_links(session, doc_nums: list[str]) -> dict[str, str]:
    """Số hiệu → URL công khai, chỉ với văn bản đã thực sự được đăng.

    Bỏ qua số hiệu trùng giữa nhiều tỉnh: không có căn cứ chọn tỉnh nào, mà trỏ
    nhầm sang văn bản của địa phương khác còn tệ hơn không có link.
    """
    if not PUBLIC_VAULT_BASE_URL or not doc_nums:
        return {}

    rows = (
        session.query(Document.doc_num, Document.public_slug)
        .filter(Document.doc_num.in_(doc_nums))
        .filter(Document.published_hash.isnot(None))
        .all()
    )
    counts: dict[str, int] = {}
    slugs: dict[str, str] = {}
    for doc_num, slug in rows:
        counts[doc_num] = counts.get(doc_num, 0) + 1
        slugs[doc_num] = slug

    return {
        num: public_url(slug)
        for num, slug in slugs.items()
        if counts[num] == 1 and slug
    }


def appendix_rows(session, report_text: str) -> list[tuple[str, str]]:
    """(số hiệu, URL) cho mọi số hiệu xuất hiện trong báo cáo.

    URL rỗng nghĩa là văn bản chưa được đăng — bên dựng PDF để text trơn.
    """
    nums = sorted(set(extract_doc_nums(report_text)))
    links = resolve_links(session, nums)
    return [(num, links.get(num, "")) for num in nums]
