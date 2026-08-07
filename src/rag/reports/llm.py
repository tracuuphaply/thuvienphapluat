"""
Gọi LLM sinh báo cáo — dùng chung cho cả ba loại.

Tách riêng vì phần xử lý `finish_reason == "length"` là an toàn-trọng yếu: báo
cáo bị cắt giữa chừng mà im lặng thì người đọc tưởng là bản đầy đủ và ra quyết
định trên một tài liệu thiếu. Nhân bản logic này ba lần chắc chắn dẫn tới ba
phiên bản trôi khác nhau.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from src.config import llm_api_key, openai_api_base, report_max_tokens, report_model

logger = logging.getLogger(__name__)

# Báo cáo dài, mô hình cần thời gian. Đây là lý do KHÔNG gọi LLM bên trong
# run_pipeline: 300 giây nằm trong khối try bao trọn pipeline nghĩa là một lỗi
# LLM sẽ đánh dấu cả lần cào là FAILED.
REQUEST_TIMEOUT = 300.0

# Thấp để bám dữ liệu; báo cáo pháp lý không cần sáng tạo.
TEMPERATURE = 0.3


class LLMUnavailable(RuntimeError):
    """Không gọi được mô hình — chưa có khoá, hoặc API lỗi."""


def strip_code_fence(text: str) -> str:
    """Gỡ khối mã bọc quanh TOÀN BỘ báo cáo.

    Prompt đã cấm dùng khối mã, nhưng mô hình vẫn thỉnh thoảng bọc cả báo cáo
    vào ```…``` — đã gặp thật ở báo cáo (c) đầu tiên. Bộ dựng PDF parse theo
    tiền tố `###`, nên một dòng ``` ở đầu file làm mọi tiêu đề chương biến thành
    văn bản thường và bố cục vỡ hoàn toàn.

    Chỉ gỡ khi hàng rào bọc CẢ báo cáo; khối mã nằm giữa nội dung thì giữ nguyên
    vì đó có thể là trích dẫn có chủ ý.
    """
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return text

    lines = stripped.splitlines()
    if len(lines) < 3 or lines[-1].strip() != "```":
        return text
    # Dòng mở có thể là "```" hoặc "```markdown"
    return "\n".join(lines[1:-1]).strip()


@dataclass
class LLMResult:
    text: str
    truncated: bool
    model: str


def call_report_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = "",
    max_tokens: int = 0,
) -> LLMResult:
    """Sinh nội dung báo cáo. Ném LLMUnavailable thay vì trả báo cáo rỗng.

    Bên gọi quyết định làm gì khi không có mô hình — nhưng KHÔNG được im lặng
    sinh ra một tài liệu trông có thẩm quyền mà không dựa trên gì.
    """
    api_key = llm_api_key()
    if not api_key:
        raise LLMUnavailable(
            "Chưa cấu hình khoá API (V98_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY)."
        )

    model_name = model or report_model()
    limit = max_tokens or report_max_tokens()
    url = f"{openai_api_base().rstrip('/')}/chat/completions"

    logger.info("Gọi mô hình %s (tối đa %d token)...", model_name, limit)
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": TEMPERATURE,
                "max_tokens": limit,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise LLMUnavailable(f"Gọi mô hình thất bại: {e}") from e

    choices = data.get("choices") or []
    if not choices:
        raise LLMUnavailable(f"Phản hồi không có nội dung: {str(data)[:300]}")

    choice = choices[0]
    text = strip_code_fence(choice["message"]["content"])
    truncated = choice.get("finish_reason") == "length"

    if truncated:
        logger.warning("Báo cáo bị cắt do chạm giới hạn %d token", limit)
        text += (
            "\n\n---\n"
            f"> ⚠️ **Báo cáo bị cắt do chạm giới hạn {limit} token.** "
            "Nội dung phía trên chưa đầy đủ. Tăng `REPORT_MAX_TOKENS` hoặc thu "
            "hẹp phạm vi chuyên đề rồi tạo lại."
        )

    return LLMResult(text=text, truncated=truncated, model=model_name)
