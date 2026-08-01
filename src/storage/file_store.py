"""
Local file storage manager.

Handles saving files to organized local directories:
  - data/tvpl/  → .docx from TVPL
  - data/moj/   → HTML fulltext + PDF from MOJ
  - data/snapshots/ → Raw JSON snapshots for diff/audit
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from src.config import MOJ_FILES_DIR, SNAPSHOTS_DIR, TVPL_FILES_DIR

logger = logging.getLogger(__name__)


def save_moj_fulltext(doc_id: str, html_content: str) -> str | None:
    """Save MOJ fulltext HTML to data/moj/{doc_id}.html."""
    if not html_content:
        return None
    path = MOJ_FILES_DIR / f"{doc_id}.html"
    path.write_text(html_content, encoding="utf-8")
    logger.debug("Saved MOJ fulltext: %s", path)
    return str(path)


METADATA_DIR = MOJ_FILES_DIR.parent / "metadata"
METADATA_DIR.mkdir(parents=True, exist_ok=True)

# Trường nội bộ của pipeline, không đưa vào file metadata bàn giao
_INTERNAL_KEYS = {"id", "event_type", "_references", "_needs_field_check"}


def save_document_metadata(doc_data: dict) -> str | None:
    """
    Lưu metadata hợp nhất của một văn bản (TVPL + Bộ Tư pháp) ra JSON.

    File này được tải lên cùng thư mục với .docx và toàn văn để mỗi thư mục
    văn bản là một hồ sơ đầy đủ, đọc được mà không cần truy cập database.
    """
    doc_num = str(doc_data.get("doc_num") or "").strip()
    if not doc_num:
        return None

    safe = re.sub(r'[\\/:*?"<>|]+', "_", doc_num)[:120]
    path = METADATA_DIR / f"{safe}.json"

    payload = {
        key: value
        for key, value in doc_data.items()
        if key not in _INTERNAL_KEYS and not key.startswith("_")
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(path)


def save_snapshot(source: str, data: dict | list) -> str:
    """
    Save a raw API/RSS snapshot for audit purposes.
    File: data/snapshots/{source}_{date}.json
    """
    today = date.today().isoformat()
    path = SNAPSHOTS_DIR / f"{source}_{today}.json"

    # Append if file exists (multiple runs per day)
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = [existing]
        except (json.JSONDecodeError, ValueError):
            existing = []

    if isinstance(data, list):
        existing.extend(data)
    else:
        existing.append(data)

    path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.debug("Saved snapshot: %s", path)
    return str(path)
