"""
Bước ĐỌC của quy trình sinh báo cáo — tóm tắt insight TỪNG văn bản.

Vì sao có bước này. Trước đây báo cáo chỉ nhận metadata (số hiệu, cơ quan, ngày
ban hành) cộng vài đoạn điều khoản rời rạc bị cắt còn 1.500 ký tự. Kết quả là
báo cáo liệt kê văn bản như một mục lục và buộc người đọc tự mở từng văn bản ra
đọc. Bước này bù đúng chỗ thiếu: với mỗi văn bản trong báo cáo, đọc HẾT toàn văn
rồi chắt ra phần có giá trị hành động (nghĩa vụ, ngưỡng, mốc thời gian, chế tài),
neo vào từng Điều/Khoản. Bước TỔNG HỢP sau đó dựng báo cáo từ các insight này
thay vì từ metadata.

Đây là map-reduce hai tầng:

  - map (trong một văn bản): văn bản dài quá một lượt gọi thì cắt thành nhiều
    phần, tóm tắt từng phần, rồi hợp nhất — nên không bao giờ tràn cửa sổ ngữ
    cảnh dù gặp đạo luật 300 Điều.
  - cache: cùng một đạo luật xuất hiện trong hàng chục báo cáo ngành và lặp lại
    mỗi quý. Bản tóm tắt được lưu theo doc_key và chỉ dựng lại khi nội dung đổi
    (content_hash) hoặc khi ta cải tiến cách tóm tắt (INSIGHT_PROMPT_VERSION).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.config import summary_max_tokens, summary_model
from src.rag.citation_check import extract_doc_nums
from src.rag.db_rag import RAGDatabase
from src.rag.reports.llm import LLMUnavailable, call_report_llm
from src.rag.reports.prompts import load_summary_prompt

logger = logging.getLogger(__name__)

# Bump khi đổi prompt_tom_tat_van_ban.md hoặc schema JSON: cache mang phiên bản
# cũ sẽ tự được dựng lại ở lần chạy sau, không cần xoá tay.
INSIGHT_PROMPT_VERSION = "v1"

# Ngân sách ký tự cho MỘT lượt gọi tóm tắt (~12k token tiếng Việt). Toàn văn dài
# hơn được cắt thành nhiều phần rồi hợp nhất.
CHAR_BUDGET = 48_000

# Các khoá hợp lệ của một bản insight. Dùng để làm sạch đầu ra mô hình.
INSIGHT_KEYS = (
    "mot_cau", "pham_vi_dieu_chinh", "noi_dung_chinh",
    "nghia_vu_moi", "moc_thoi_gian", "che_tai", "diem_dang_chu_y",
)


@dataclass
class InsightBundle:
    """Kết quả bước ĐỌC cho một nhóm văn bản.

    `items` nạp thẳng vào payload báo cáo; hai danh sách còn lại nạp vào khối
    hạn chế dữ liệu để báo cáo nói thật chỗ nào chưa đọc sâu được.
    """
    items: list[dict[str, Any]] = field(default_factory=list)
    khong_co_toan_van: list[str] = field(default_factory=list)  # không có chunk
    loi_tom_tat: list[str] = field(default_factory=list)        # gọi/parse hỏng
    # Mọi số hiệu XUẤT HIỆN trong toàn văn các văn bản đã đọc. Đây là nhóm số
    # hiệu có thật mà kho có thể chưa có bản ghi (vd văn bản cũ bị bãi bỏ) — cổng
    # kiểm trích dẫn dùng nó để không chặn nhầm. Lấy TỪ NGUỒN, không từ insight
    # do mô hình sinh, nên không thể bị mô hình bịa lọt qua.
    source_doc_nums: set[str] = field(default_factory=set)


# ──────────────────────────────────────────────
# Tiện ích thuần — không gọi mô hình, dễ test
# ──────────────────────────────────────────────
def content_hash(chunks: list[dict[str, Any]]) -> str:
    """Vân tay nội dung toàn văn, để biết khi nào cần tóm tắt lại."""
    h = hashlib.sha256()
    for c in chunks:
        h.update((c.get("heading") or "").encode("utf-8"))
        h.update(b"\x00")
        h.update((c.get("content") or "").encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


def _chunk_text(chunk: dict[str, Any]) -> str:
    """Một đoạn ở dạng đưa cho mô hình đọc. content đã gồm heading (xem

    text_processor._split_by_pattern), nên chỉ lùi về heading khi content rỗng.
    """
    body = (chunk.get("content") or "").strip()
    return body or (chunk.get("heading") or "").strip()


def _batches(chunks: list[dict[str, Any]], budget: int) -> list[list[dict[str, Any]]]:
    """Gom đoạn thành từng mẻ, mỗi mẻ không vượt ngân sách ký tự.

    Một đoạn đơn lẻ vượt ngân sách vẫn đứng riêng một mẻ — cắt ngang một Điều là
    mất đúng phần chi tiết cần tóm tắt, mà một Điều hiếm khi vượt cửa sổ ngữ cảnh.
    """
    out: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    size = 0
    for c in chunks:
        n = len(_chunk_text(c))
        if cur and size + n > budget:
            out.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += n
    if cur:
        out.append(cur)
    return out


def _join(chunks: list[dict[str, Any]]) -> str:
    return "\n\n".join(_chunk_text(c) for c in chunks if _chunk_text(c))


def parse_insight(text: str) -> dict[str, Any]:
    """Bóc JSON từ phản hồi mô hình, chịu được rác quanh khối JSON.

    Lấy từ dấu `{` đầu tới `}` cuối rồi mới json.loads: mô hình đôi khi thêm một
    câu dẫn nhập dù prompt cấm, và call_report_llm có thể nối cảnh báo cắt token
    vào cuối. Ném ValueError nếu không có JSON hợp lệ — bên gọi ghi vào loi_tom_tat.
    """
    s = (text or "").strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("phản hồi không chứa khối JSON")
    obj = json.loads(s[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("JSON không phải đối tượng")
    return _clean(obj)


def _clean(obj: dict[str, Any]) -> dict[str, Any]:
    """Chỉ giữ các khoá trong schema, ép kiểu list cho các trường mảng."""
    out: dict[str, Any] = {}
    for k in INSIGHT_KEYS:
        if k not in obj:
            continue
        v = obj[k]
        if k in ("mot_cau", "pham_vi_dieu_chinh"):
            out[k] = str(v).strip()
        else:
            out[k] = v if isinstance(v, list) else ([v] if v else [])
    return out


def _is_thin(insight: dict[str, Any]) -> bool:
    """Insight rỗng ruột: không có ý chính nào. Coi như tóm tắt hỏng."""
    return not insight.get("noi_dung_chinh")


# ──────────────────────────────────────────────
# Gọi mô hình
# ──────────────────────────────────────────────
def _summarize_block(system: str, text_block: str, doc_num: str, title: str,
                     model: str, is_merge: bool = False) -> dict[str, Any]:
    if is_merge:
        head = (
            f"Văn bản: {doc_num} — {title}\n"
            "Đầu vào dưới đây là CÁC BẢN TÓM TẮT BỘ PHẬN của cùng một văn bản, "
            "cần hợp nhất thành một JSON theo schema.\n\n"
        )
    else:
        head = (
            f"Văn bản: {doc_num} — {title}\n"
            "Toàn văn (theo thứ tự Điều/Khoản):\n\n"
        )
    result = call_report_llm(
        system, head + text_block, model=model, max_tokens=summary_max_tokens()
    )
    if result.truncated:
        # JSON bị cắt giữa chừng thì parse sẽ hỏng và nội dung thiếu — coi là lỗi
        # thay vì cố vá một bản dở.
        raise LLMUnavailable(f"tóm tắt {doc_num} bị cắt do chạm giới hạn token")
    return parse_insight(result.text)


def summarize_chunks(chunks: list[dict[str, Any]], doc_num: str, title: str,
                     model: str = "") -> dict[str, Any]:
    """Tóm tắt toàn văn một văn bản thành insight có cấu trúc.

    Văn bản vừa một lượt gọi thì gọi thẳng; dài hơn thì map-reduce: tóm tắt từng
    mẻ rồi hợp nhất. Ném LLMUnavailable/ValueError khi mô hình hỏng — bên gọi
    quyết định ghi nhận thế nào.
    """
    system = load_summary_prompt()
    model = model or summary_model()
    batches = _batches(chunks, CHAR_BUDGET)

    if len(batches) <= 1:
        return _summarize_block(system, _join(chunks), doc_num, title, model)

    partials: list[dict[str, Any]] = []
    for i, batch in enumerate(batches, 1):
        logger.info("Tóm tắt %s: phần %d/%d", doc_num, i, len(batches))
        partials.append(
            _summarize_block(system, _join(batch), doc_num,
                             f"{title} (phần {i}/{len(batches)})", model)
        )
    merged_input = "\n\n".join(
        json.dumps(p, ensure_ascii=False, indent=2) for p in partials
    )
    return _summarize_block(system, merged_input, doc_num, title, model,
                            is_merge=True)


# ──────────────────────────────────────────────
# Điểm vào có cache
# ──────────────────────────────────────────────
def insight_for_document(rag: RAGDatabase, doc_key: str, doc_num: str,
                         title: str, model: str = "",
                         force: bool = False) -> dict[str, Any] | None:
    """Insight của một văn bản, ưu tiên cache. None nếu văn bản không có toàn văn.

    Cache hợp lệ khi content_hash và prompt_version trùng. Đổi model KHÔNG làm
    mất hiệu lực cache — hai model đều cho bản tóm tắt dùng được, và tóm tắt lại
    cả kho chỉ vì đổi model là lãng phí; muốn ép làm mới thì truyền force=True.
    """
    chunks = rag.full_document(doc_key)
    if not chunks:
        return None

    chash = content_hash(chunks)
    if not force:
        cached = rag.get_document_insight(doc_key)
        if (cached and cached.get("content_hash") == chash
                and cached.get("prompt_version") == INSIGHT_PROMPT_VERSION):
            try:
                return _clean(json.loads(cached["insight_json"]))
            except (ValueError, KeyError, TypeError):
                logger.warning("Cache insight %s hỏng, tóm tắt lại", doc_num)

    model = model or summary_model()
    insight = summarize_chunks(chunks, doc_num, title, model=model)
    source_chars = sum(len(_chunk_text(c)) for c in chunks)
    rag.save_document_insight(
        doc_key=doc_key, doc_num=doc_num, content_hash=chash,
        prompt_version=INSIGHT_PROMPT_VERSION, model=model,
        insight_json=json.dumps(insight, ensure_ascii=False),
        source_chars=source_chars,
    )
    return insight


def build_insights(rag: RAGDatabase, docs: list[Any],
                   model: str = "") -> InsightBundle:
    """Bước ĐỌC cho một nhóm văn bản (các đối tượng Document).

    Một văn bản tóm tắt hỏng KHÔNG làm hỏng cả báo cáo: ghi vào loi_tom_tat để
    báo cáo công bố là chưa đọc sâu được, rồi đọc tiếp văn bản sau. Im lặng bỏ
    qua mới là điều nguy hiểm — báo cáo trông vẫn đầy đủ.
    """
    bundle = InsightBundle()
    for doc in docs:
        doc_key = getattr(doc, "doc_key", None) or getattr(doc, "doc_num", "")
        doc_num = getattr(doc, "doc_num", "") or ""
        title = getattr(doc, "title", "") or ""

        # Thu số hiệu từ TOÀN VĂN nguồn — làm trước và độc lập với việc tóm tắt.
        # Kể cả khi tóm tắt hỏng, các số hiệu văn bản cũ bị bãi bỏ/dẫn chiếu vẫn
        # là số thật, phải được cổng trích dẫn chấp nhận.
        for c in rag.full_document(doc_key):
            bundle.source_doc_nums.update(extract_doc_nums(c.get("content") or ""))
            bundle.source_doc_nums.update(extract_doc_nums(c.get("heading") or ""))

        try:
            insight = insight_for_document(rag, doc_key, doc_num, title, model=model)
        except (LLMUnavailable, ValueError, KeyError) as e:
            logger.warning("Không tóm tắt được %s: %s", doc_num, e)
            bundle.loi_tom_tat.append(doc_num)
            continue

        if insight is None:
            bundle.khong_co_toan_van.append(doc_num)
        elif _is_thin(insight):
            bundle.loi_tom_tat.append(doc_num)
        else:
            bundle.items.append({"doc_num": doc_num, "title": title, **insight})
    return bundle


__all__ = [
    "INSIGHT_PROMPT_VERSION", "InsightBundle",
    "build_insights", "insight_for_document", "summarize_chunks",
    "content_hash", "parse_insight",
]
