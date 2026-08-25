"""Nạp mẫu prompt cho ba loại báo cáo, có cơ chế include phần dùng chung."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from src.config import PROJECT_ROOT, report_prompt_path

logger = logging.getLogger(__name__)

PROMPT_DIR = PROJECT_ROOT / "src" / "rag" / "prompts"

# Loại báo cáo → file mẫu.
KIND_TO_FILE: dict[str, str] = {
    "a": "prompt_bao_cao_v98.md",       # tổng hợp ngành
    "b": "prompt_cap_nhat_van_ban.md",  # phân tích văn bản mới
    "c": "prompt_tac_dong_nganh.md",    # doanh nghiệp trong ngành
}

# Mẫu cho bước ĐỌC — tóm tắt insight từng văn bản, dùng trước cả ba loại báo cáo.
SUMMARY_FILE = "prompt_tom_tat_van_ban.md"

# Mẫu sinh thân bài Cẩm nang cho một biểu mẫu — đầu vào của bộ nhập bên
# xuất bản. Không phải "loại báo cáo": đầu ra là bài web, không có PDF.
CAM_NANG_FILE = "prompt_cam_nang_bieu_mau.md"

# Mục 9 trở đi là tài liệu cho người vận hành (hợp đồng dữ liệu, tham số API),
# không phải chỉ dẫn cho mô hình. Mỗi mẫu tự khai chỗ cắt bằng tiêu đề này.
_CUT_MARKERS = ("## 9. HỢP ĐỒNG DỮ LIỆU", "## 7. HỢP ĐỒNG DỮ LIỆU")

_INCLUDE = re.compile(r"\{\{include:([^}]+)\}\}")


class PromptTemplateMissing(RuntimeError):
    """Không đọc được mẫu prompt — không được sinh báo cáo bằng prompt rút gọn.

    Trước đây thiếu file thì hàm trả về một câu mô tả vai trò một dòng và báo cáo
    vẫn ra, mất toàn bộ cấu trúc bắt buộc, quy tắc trích dẫn và điều cấm — mà
    người dùng không hề biết.
    """


def _expand_includes(text: str, depth: int = 0) -> str:
    if depth > 3:
        raise PromptTemplateMissing("include lồng quá sâu — nghi ngờ vòng lặp")

    def replace(match: re.Match) -> str:
        target = PROMPT_DIR / match.group(1).strip()
        try:
            return _expand_includes(target.read_text(encoding="utf-8"), depth + 1)
        except OSError as e:
            raise PromptTemplateMissing(f"Không đọc được phần dùng chung {target}: {e}")

    return _INCLUDE.sub(replace, text)


def load_prompt(kind: str = "a") -> str:
    """Phần chỉ dẫn dành cho mô hình của một loại báo cáo.

    Biến REPORT_PROMPT_PATH chỉ ghi đè mẫu (a) — đó là mẫu duy nhất người vận
    hành có nhu cầu thay ngoài repo.
    """
    candidates: list[Path] = []
    override = report_prompt_path()
    if kind == "a" and override:
        candidates.append(Path(override))
    if kind in KIND_TO_FILE:
        candidates.append(PROMPT_DIR / KIND_TO_FILE[kind])

    for path in candidates:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        content = _expand_includes(content)
        for marker in _CUT_MARKERS:
            cut = content.find(marker)
            if cut > 0:
                return content[:cut].rstrip()
        return content

    raise PromptTemplateMissing(
        f"Không đọc được mẫu prompt loại {kind!r} tại: {[str(p) for p in candidates]}"
    )


def load_summary_prompt() -> str:
    """Mẫu hệ thống cho bước tóm tắt insight một văn bản.

    Tách khỏi load_prompt vì đây không phải một "loại báo cáo": nó là bước ĐỌC
    chạy trước, và không có khối HỢP ĐỒNG DỮ LIỆU để cắt.
    """
    path = PROMPT_DIR / SUMMARY_FILE
    try:
        return _expand_includes(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise PromptTemplateMissing(f"Không đọc được mẫu tóm tắt {path}: {e}")


def load_cam_nang_prompt() -> str:
    """Mẫu hệ thống cho bước SINH THÂN BÀI Cẩm nang của một biểu mẫu.

    Đi qua đúng cơ chế `{{include:…}}` của báo cáo để tái dùng nguyên văn hai
    phần dùng chung (giọng văn, điều cấm) — nhân bản chúng lần thứ tư là cách
    chắc chắn nhất để bốn bản trôi khác nhau.

    KHÔNG cắt ở `_CUT_MARKERS`: mẫu này không có khối HỢP ĐỒNG DỮ LIỆU dành cho
    người vận hành, mọi mục trong nó đều là chỉ dẫn cho mô hình.
    """
    path = PROMPT_DIR / CAM_NANG_FILE
    try:
        return _expand_includes(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise PromptTemplateMissing(f"Không đọc được mẫu Cẩm nang {path}: {e}")
