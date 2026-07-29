"""
Telegram Bot notification — daily digest builder & sender.

Formats a daily summary of new/changed business legal documents
and sends it to a configured Telegram group chat.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from src.config import (
    BUSINESS_FIELDS,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

logger = logging.getLogger(__name__)

# Event type labels
EVENT_LABELS = {
    "A": "🆕 Mới ban hành",
    "B": "🔄 Đổi hiệu lực",
    "C": "✏️ Bị sửa đổi/thay thế",
}


def build_daily_digest(documents: list[dict[str, Any]]) -> str:
    """
    Build a Telegram message (Markdown format) summarizing today's documents.
    """
    today = date.today().strftime("%d/%m/%Y")
    if not documents:
        return f"📋 *VĂN BẢN DOANH NGHIỆP — {today}*\n\n✅ Không có văn bản mới hôm nay."

    lines = [f"📋 *VĂN BẢN DOANH NGHIỆP MỚI — {today}*\n"]

    # Group by event type
    by_event: dict[str, list] = {"A": [], "B": [], "C": []}
    for doc in documents:
        evt = doc.get("event_type", "A")
        by_event.setdefault(evt, []).append(doc)

    for evt_type in ["A", "B", "C"]:
        evt_docs = by_event.get(evt_type, [])
        if not evt_docs:
            continue

        label = EVENT_LABELS.get(evt_type, "📌")
        lines.append(f"\n*{label}* ({len(evt_docs)} văn bản)")
        lines.append("━━━━━━━━━━━━━━━━")

        for doc in evt_docs:
            doc_num = doc.get("doc_num", "N/A")
            title = doc.get("title", "")
            # Truncate long titles
            if len(title) > 120:
                title = title[:117] + "..."

            agency = doc.get("agency_name", "")
            issue_date = doc.get("issue_date", "")
            if hasattr(issue_date, "strftime"):
                issue_date = issue_date.strftime("%d/%m/%Y")

            eff_status = doc.get("eff_status", "")
            field_name = doc.get("field_name", "")

            lines.append(f"\n📌 *{_escape_md(doc_num)}*")
            if title and title != doc_num:
                lines.append(f"_{_escape_md(title)}_")
            if agency:
                lines.append(f"🏛 {_escape_md(agency)}")

            info_parts = []
            if issue_date:
                info_parts.append(f"📅 {issue_date}")
            if eff_status:
                info_parts.append(f"⚡ {_escape_md(eff_status)}")
            if field_name:
                info_parts.append(f"📂 {_escape_md(field_name)}")
            if info_parts:
                lines.append(" | ".join(info_parts))

            # Google Drive links
            gdrive_docx = doc.get("gdrive_docx_link")
            gdrive_pdf = doc.get("gdrive_pdf_link")
            link_parts = []
            if gdrive_docx:
                link_parts.append(f"[📁 Tải .docx]({gdrive_docx})")
            if gdrive_pdf:
                link_parts.append(f"[📄 Xem PDF]({gdrive_pdf})")

            # Source links
            tvpl_url = doc.get("tvpl_url")
            moj_url = doc.get("moj_url")
            if tvpl_url:
                link_parts.append(f"[🔗 TVPL]({tvpl_url})")
            if moj_url:
                link_parts.append(f"[🔗 MOJ]({moj_url})")

            if link_parts:
                lines.append(" | ".join(link_parts))

    # Summary footer
    count_a = len(by_event.get("A", []))
    count_b = len(by_event.get("B", []))
    count_c = len(by_event.get("C", []))
    lines.append(f"\n━━━━━━━━━━━━━━━━")
    lines.append(
        f"📊 *Tổng:* {count_a} mới | {count_b} đổi hiệu lực | {count_c} sửa/thay"
    )

    return "\n".join(lines)


def _escape_md(text: str) -> str:
    """Escape special Markdown characters for Telegram."""
    # Telegram MarkdownV2 special chars
    special = r"_*[]()~`>#+-=|{}.!"
    result = ""
    for c in text:
        if c in special:
            result += f"\\{c}"
        else:
            result += c
    return result


async def send_message_async(
    chat_id: str, text: str, parse_mode: str = "Markdown"
) -> bool:
    """Send a message via Telegram Bot API (async)."""
    import httpx

    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram bot token not configured.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Split long messages (Telegram limit: 4096 chars)
    chunks = _split_message(text, 4000)

    try:
        async with httpx.AsyncClient() as client:
            for chunk in chunks:
                resp = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
                if resp.status_code != 200:
                    logger.error(
                        "Telegram send failed: %s %s",
                        resp.status_code,
                        resp.text,
                    )
                    return False
        return True
    except Exception as e:
        logger.error("Telegram send error: %s", e)
        return False


def send_message_sync(
    chat_id: str, text: str, parse_mode: str = "Markdown"
) -> bool:
    """Send a message via Telegram Bot API (synchronous)."""
    import httpx

    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram bot token not configured.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = _split_message(text, 4000)

    try:
        with httpx.Client() as client:
            for chunk in chunks:
                resp = client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
                if resp.status_code != 200:
                    logger.error(
                        "Telegram send failed: %s %s",
                        resp.status_code,
                        resp.text,
                    )
                    return False
        return True
    except Exception as e:
        logger.error("Telegram send error: %s", e)
        return False


def send_daily_digest(documents: list[dict[str, Any]]) -> bool:
    """Build and send the daily digest to the configured chat."""
    message = build_daily_digest(documents)
    chat_id = TELEGRAM_CHAT_ID
    if not chat_id:
        logger.warning("TELEGRAM_CHAT_ID not configured.")
        return False
    return send_message_sync(chat_id, message)


def send_error_alert(error_message: str) -> bool:
    """Send an error alert to the admin chat."""
    admin_id = TELEGRAM_ADMIN_CHAT_ID or TELEGRAM_CHAT_ID
    if not admin_id:
        return False

    text = (
        f"🚨 *CẢNH BÁO HỆ THỐNG*\n\n"
        f"Pipeline gặp lỗi:\n"
        f"`{_escape_md(error_message[:500])}`\n\n"
        f"Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    return send_message_sync(admin_id, text)


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long message into chunks respecting Telegram's limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at a newline
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
