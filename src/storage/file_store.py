"""
Local file storage manager.

Handles saving files to organized local directories:
  - data/tvpl/  → .docx/.pdf from TVPL
  - data/moj/   → HTML fulltext + PDF from MOJ
  - data/snapshots/ → Raw JSON snapshots for diff/audit
"""
from __future__ import annotations

import json
import logging
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
