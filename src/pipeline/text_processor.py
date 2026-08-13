"""
Legal document text processor — HTML → Clean Markdown → Legal Chunks.

Processes raw HTML fulltext from MOJ API into:
  1. Clean Markdown (stripped of HTML tags, normalized whitespace)
  2. Legal Chunks (split by Điều/Khoản/Mục structure)

This prepares data for Phase 2 (RAG Chatbot + Vector Database).

Chunking Strategy:
  - Primary split: by "Điều" (Article) headings → each Điều is one chunk
  - Fallback split: by "Chương" (Chapter) if Điều not found
  - Each chunk carries metadata: doc_num, chunk_index, heading, char_count
  - Target chunk size: 500-2000 chars (optimal for embedding models)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

# Directory for processed clean text
CLEAN_TEXT_DIR = DATA_DIR / "clean_text"
CHUNKS_DIR = DATA_DIR / "chunks"
CLEAN_TEXT_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# HTML → Clean Markdown
# ──────────────────────────────────────────────
# Dưới ngưỡng này thì coi như không có nội dung. Gateway Bộ Tư pháp trả về một
# khung HTML rỗng (`<body></body>`, 83 byte) cho những văn bản nó không có toàn
# văn, thay vì báo lỗi. Ghi nhận nó là "đã có toàn văn" tạo ra một dữ kiện sai:
# 163 văn bản từng khai có toàn văn mà không một chữ nào.
MIN_FULLTEXT_CHARS = 200


def has_meaningful_fulltext(html: str) -> bool:
    """Nội dung HTML có đủ chữ để coi là toàn văn không?

    Xét trên văn bản đã bóc thẻ chứ không xét độ dài HTML: một khung rỗng vẫn
    dài vài chục byte, còn một trang đầy thẻ định dạng có thể ít chữ.
    """
    return len(html_to_clean_text(html or "").strip()) >= MIN_FULLTEXT_CHARS


def html_to_clean_text(html: str) -> str:
    """
    Convert raw HTML fulltext to clean plain text / light Markdown.

    Handles typical MOJ HTML: <p>, <br>, <table>, <b>, <i>, nested divs,
    inline styles, empty tags, etc.
    """
    if not html or not html.strip():
        return ""

    text = html

    # 1. Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Convert block-level elements to newlines
    # <br>, <br/>, <br />
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # </p>, </div>, </li>, </tr>, </h1-6>
    text = re.sub(
        r"</(?:p|div|li|tr|h[1-6]|blockquote|section|article)>",
        "\n\n",
        text,
        flags=re.IGNORECASE,
    )
    # <hr> → horizontal rule
    text = re.sub(r"<hr\s*/?>", "\n---\n", text, flags=re.IGNORECASE)

    # 3. Convert inline formatting
    # <b>, <strong> → **bold**
    text = re.sub(
        r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>",
        r"**\1**",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # <i>, <em> → *italic*
    text = re.sub(
        r"<(?:i|em)[^>]*>(.*?)</(?:i|em)>",
        r"*\1*",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 4. Handle tables (basic: extract cell text separated by | )
    text = re.sub(r"<td[^>]*>", "| ", text, flags=re.IGNORECASE)
    text = re.sub(r"</td>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<th[^>]*>", "| **", text, flags=re.IGNORECASE)
    text = re.sub(r"</th>", "** ", text, flags=re.IGNORECASE)

    # 5. Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # 6. Decode common HTML entities
    entity_map = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
        "&ndash;": "–",
        "&mdash;": "—",
        "&hellip;": "…",
        "&lsquo;": "'",
        "&rsquo;": "'",
        "&ldquo;": "\u201c",
        "&rdquo;": "\u201d",
    }
    for entity, char in entity_map.items():
        text = text.replace(entity, char)
    # Numeric entities. chr() ném ValueError nếu điểm mã vượt 0x10FFFF; một
    # "&#9999999999;" rác trong HTML sẽ làm hỏng cả văn bản (đánh dấu FAILED,
    # mất toàn bộ toàn văn). Ngoài dải hợp lệ thì bỏ thực thể đó.
    def _ky_tu_so(code: int) -> str:
        return chr(code) if 0 < code <= 0x10FFFF else ""

    text = re.sub(r"&#(\d+);", lambda m: _ky_tu_so(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9a-fA-F]+);",
                  lambda m: _ky_tu_so(int(m.group(1), 16)), text)

    # 7. Normalize whitespace
    # Collapse multiple spaces (but not newlines) into single space
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Remove leading/trailing whitespace from the whole text
    text = text.strip()

    return text


# ──────────────────────────────────────────────
# Legal Chunking (split by Điều / Chương)
# ──────────────────────────────────────────────

# Regex patterns for Vietnamese legal structure
_DIEU_PATTERN = re.compile(
    r"^(?:\*{0,2})\s*Điều\s+(\d+[a-z]?)\s*[.:]\s*(.*?)(?:\*{0,2})$",
    re.MULTILINE | re.IGNORECASE,
)

_CHUONG_PATTERN = re.compile(
    r"^(?:\*{0,2})\s*Chương\s+([IVXLCDM\d]+)\s*[.:]\s*(.*?)(?:\*{0,2})$",
    re.MULTILINE | re.IGNORECASE,
)

_MUC_PATTERN = re.compile(
    r"^(?:\*{0,2})\s*Mục\s+(\d+)\s*[.:]\s*(.*?)(?:\*{0,2})$",
    re.MULTILINE | re.IGNORECASE,
)


def chunk_legal_text(
    clean_text: str,
    doc_num: str = "",
    max_chunk_size: int = 2000,
    min_chunk_size: int = 100,
) -> list[dict[str, Any]]:
    """
    Split legal text into semantic chunks by Điều (Article).

    Each chunk is a dict:
      {
          "doc_num": "12/2026/NĐ-CP",
          "chunk_index": 0,
          "heading": "Điều 1. Phạm vi điều chỉnh",
          "content": "Nghị định này quy định...",
          "char_count": 850,
          "chunk_type": "dieu",        # dieu | chuong | preamble | full
      }

    Strategy:
      1. Try splitting by "Điều N." markers (most granular)
      2. If no Điều found, try splitting by "Chương" (Chapter)
      3. If still no structure found, return the whole text as 1 chunk
    """
    if not clean_text or len(clean_text) < min_chunk_size:
        return [_make_chunk(doc_num, 0, "Toàn văn", clean_text, "full")]

    # Try Điều-level chunking first
    chunks = _split_by_pattern(clean_text, _DIEU_PATTERN, "dieu", doc_num)
    if len(chunks) >= 2:
        return _enforce_size_limits(chunks, max_chunk_size, min_chunk_size)

    # Fallback: Chương-level
    chunks = _split_by_pattern(clean_text, _CHUONG_PATTERN, "chuong", doc_num)
    if len(chunks) >= 2:
        return _enforce_size_limits(chunks, max_chunk_size, min_chunk_size)

    # No recognizable structure — vẫn phải áp trần kích thước, nếu không một văn
    # bản không có cấu trúc Điều/Chương thành đúng MỘT chunk khổng lồ, về sau bị
    # cắt cụt lúc nhúng vector. (Nhánh này trước đây bỏ qua _enforce_size_limits.)
    return _enforce_size_limits(
        [_make_chunk(doc_num, 0, "Toàn văn", clean_text, "full")],
        max_chunk_size, min_chunk_size,
    )


def _split_by_pattern(
    text: str,
    pattern: re.Pattern,
    chunk_type: str,
    doc_num: str,
) -> list[dict[str, Any]]:
    """Split text by a regex pattern into sequential chunks."""
    matches = list(pattern.finditer(text))
    if not matches:
        return []

    chunks = []

    # Preamble (text before first match)
    preamble = text[: matches[0].start()].strip()
    if preamble and len(preamble) > 50:
        chunks.append(
            _make_chunk(doc_num, 0, "Phần mở đầu", preamble, "preamble")
        )

    # Each matched section
    for i, match in enumerate(matches):
        section_num = match.group(1)
        section_title = match.group(2).strip()
        heading_prefix = "Điều" if chunk_type == "dieu" else "Chương"
        heading = f"{heading_prefix} {section_num}"
        if section_title:
            heading += f". {section_title}"

        # Content = from this match to the next match (or end of text)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        # Include the heading line itself in the content
        full_content = f"{heading}\n\n{content}" if content else heading

        chunk_index = len(chunks)
        chunks.append(
            _make_chunk(doc_num, chunk_index, heading, full_content, chunk_type)
        )

    return chunks


def _make_chunk(
    doc_num: str,
    chunk_index: int,
    heading: str,
    content: str,
    chunk_type: str,
) -> dict[str, Any]:
    """Create a single chunk dict."""
    return {
        "doc_num": doc_num,
        "chunk_index": chunk_index,
        "heading": heading,
        "content": content,
        "char_count": len(content),
        "chunk_type": chunk_type,
    }


def _enforce_size_limits(
    chunks: list[dict[str, Any]],
    max_size: int,
    min_size: int,
) -> list[dict[str, Any]]:
    """
    Post-process chunks:
      - Merge very small chunks into their predecessor
      - Split very large chunks at paragraph boundaries
    """
    result = []
    for chunk in chunks:
        if chunk["char_count"] > max_size:
            # Split at paragraph boundaries (\n\n)
            sub_chunks = _split_large_chunk(chunk, max_size)
            result.extend(sub_chunks)
        elif chunk["char_count"] < min_size and result:
            # Merge into previous chunk
            prev = result[-1]
            prev["content"] += "\n\n" + chunk["content"]
            prev["char_count"] = len(prev["content"])
        else:
            result.append(chunk)

    # Re-index
    for i, chunk in enumerate(result):
        chunk["chunk_index"] = i

    return result


def _split_large_chunk(
    chunk: dict[str, Any], max_size: int
) -> list[dict[str, Any]]:
    """Split a single large chunk at double-newline boundaries."""
    text = chunk["content"]
    paragraphs = text.split("\n\n")
    sub_chunks = []
    current_text = ""

    for para in paragraphs:
        # Đoạn đơn lẻ đã vượt trần: đẩy phần đang gom ra rồi CẮT CỨNG đoạn này
        # theo max_size. Không có nhánh này thì một đoạn dài liền mạch (không có
        # \n\n) thành đúng một sub-chunk quá cỡ — thứ hàm này sinh ra để chặn,
        # và về sau bị cắt cụt lúc nhúng vector.
        if len(para) > max_size:
            if current_text.strip():
                sub_chunks.append(_make_chunk(
                    chunk["doc_num"], 0, chunk["heading"],
                    current_text.strip(), chunk["chunk_type"]))
                current_text = ""
            for i in range(0, len(para), max_size):
                sub_chunks.append(_make_chunk(
                    chunk["doc_num"], 0, chunk["heading"],
                    para[i:i + max_size].strip(), chunk["chunk_type"]))
            continue
        if len(current_text) + len(para) + 2 > max_size and current_text:
            sub_chunks.append(
                _make_chunk(
                    chunk["doc_num"],
                    0,  # Will be re-indexed later
                    chunk["heading"],
                    current_text.strip(),
                    chunk["chunk_type"],
                )
            )
            current_text = para
        else:
            current_text += ("\n\n" if current_text else "") + para

    if current_text.strip():
        sub_chunks.append(
            _make_chunk(
                chunk["doc_num"],
                0,
                chunk["heading"],
                current_text.strip(),
                chunk["chunk_type"],
            )
        )

    return sub_chunks


# ──────────────────────────────────────────────
# Pipeline Integration Functions
# ──────────────────────────────────────────────
def process_fulltext(
    doc_id: str,
    html_content: str,
    doc_num: str = "",
) -> dict[str, Any]:
    """
    Full processing pipeline: HTML → Clean Text → Chunks → Save files.

    Returns:
      {
          "clean_text_path": str,
          "chunks_path": str,
          "chunk_count": int,
          "char_count": int,
      }
    """
    result = {
        "clean_text_path": None,
        "chunks_path": None,
        "chunk_count": 0,
        "char_count": 0,
    }

    if not html_content:
        return result

    # Step 1: HTML → Clean text
    clean_text = html_to_clean_text(html_content)
    if not clean_text:
        return result

    # Step 2: Save clean text
    clean_path = CLEAN_TEXT_DIR / f"{doc_id}.md"
    clean_path.write_text(clean_text, encoding="utf-8")
    result["clean_text_path"] = str(clean_path)
    result["char_count"] = len(clean_text)

    # Step 3: Chunk by legal structure
    chunks = chunk_legal_text(clean_text, doc_num=doc_num)
    result["chunk_count"] = len(chunks)

    # Step 4: Save chunks as JSON
    chunks_path = CHUNKS_DIR / f"{doc_id}_chunks.json"
    chunks_path.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["chunks_path"] = str(chunks_path)

    logger.info(
        "Processed fulltext for %s: %d chars → %d chunks",
        doc_id or doc_num,
        len(clean_text),
        len(chunks),
    )

    return result


# ──────────────────────────────────────────────
# CLI entry point for testing
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test with a sample HTML
    sample_html = """
    <div class="content">
        <p><b>CHÍNH PHỦ</b></p>
        <p>Căn cứ Luật Tổ chức Chính phủ ngày 19 tháng 6 năm 2015;</p>
        <p><b>Chương I. QUY ĐỊNH CHUNG</b></p>
        <p><b>Điều 1. Phạm vi điều chỉnh</b></p>
        <p>Nghị định này quy định chi tiết một số điều và biện pháp thi hành
        Luật Doanh nghiệp về đăng ký doanh nghiệp; đăng ký hộ kinh doanh.</p>
        <p><b>Điều 2. Đối tượng áp dụng</b></p>
        <p>1. Tổ chức, cá nhân trong nước; tổ chức, cá nhân nước ngoài
        thực hiện đăng ký doanh nghiệp theo quy định của Luật Doanh nghiệp.</p>
        <p>2. Cơ quan đăng ký kinh doanh.</p>
        <p><b>Điều 3. Giải thích từ ngữ</b></p>
        <p>Trong Nghị định này, các từ ngữ dưới đây được hiểu như sau:</p>
        <p>1. &ldquo;Hệ thống thông tin quốc gia về đăng ký doanh nghiệp&rdquo;
        là hệ thống thông tin nghiệp vụ chuyên môn.</p>
    </div>
    """

    print("=== HTML → Clean Text ===\n")
    clean = html_to_clean_text(sample_html)
    print(clean)
    print("\n=== Legal Chunks ===\n")
    chunks = chunk_legal_text(clean, doc_num="01/2021/NĐ-CP")
    for c in chunks:
        print(f"[{c['chunk_type']}] {c['heading']} ({c['char_count']} chars)")
        print(f"  {c['content'][:100]}...")
        print()
    print(f"Total: {len(chunks)} chunks")
