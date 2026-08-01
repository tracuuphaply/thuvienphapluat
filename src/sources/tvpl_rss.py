"""
TVPL (thuvienphapluat.vn) RSS feed parser.

Reads the public RSS feed, filters items by business field slugs
in the URL, and returns normalized document triggers.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from src.config import BUSINESS_FIELD_SLUGS, TVPL_RSS_URL

logger = logging.getLogger(__name__)


def fetch_rss(url: str = TVPL_RSS_URL) -> list[dict[str, Any]]:
    """
    Fetch and parse the TVPL RSS feed.
    Returns all entries as raw dicts.
    """
    logger.info("Fetching TVPL RSS from %s", url)
    feed = feedparser.parse(url)

    if feed.bozo:
        logger.warning("RSS parse warning: %s", feed.bozo_exception)

    logger.info("RSS fetched: %d total items", len(feed.entries))
    return feed.entries


def extract_tvpl_id(url: str) -> str | None:
    """
    Extract the TVPL document ID from a URL.
    The ID is the last number in the slug before .aspx.
    Example: https://thuvienphapluat.vn/van-ban/Doanh-nghiep/...-716326.aspx → '716326'
    """
    match = re.search(r"-(\d+)\.aspx", url)
    return match.group(1) if match else None


def extract_field_slug(url: str) -> str | None:
    """
    Extract the field slug from a TVPL URL.
    Example: /van-ban/Doanh-nghiep/... → 'Doanh-nghiep'
    """
    match = re.search(r"/van-ban/([^/]+)/", url)
    return match.group(1) if match else None


def is_business_item(entry: dict) -> bool:
    """
    Check if an RSS item belongs to a business-related field.
    Checks: URL slug, category tags.
    """
    link = entry.get("link", "")
    slug = extract_field_slug(link)
    if slug and slug in BUSINESS_FIELD_SLUGS:
        return True

    # Also check category/tags
    for tag in entry.get("tags", []):
        term = tag.get("term", "")
        if term in BUSINESS_FIELD_SLUGS:
            return True

    # Check category field directly
    category = entry.get("category", "")
    if category in BUSINESS_FIELD_SLUGS:
        return True

    return False


def _parse_pub_date(raw: str) -> date | None:
    """Chuyển ngày RFC 822 của RSS ('Mon, 21 Jul 2026 10:00:00 GMT') sang date."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        return None


def parse_rss_entry(entry: dict) -> dict[str, Any]:
    """
    Parse a single RSS entry into a normalized document trigger dict.
    """
    link = entry.get("link", "")
    tvpl_id = extract_tvpl_id(link)
    slug = extract_field_slug(link)
    field_code = BUSINESS_FIELD_SLUGS.get(slug) if slug else None

    # Extract doc_num from title — typically the title IS the doc number
    title = (entry.get("title", "") or "").strip()

    # Parse publication date (RFC 822 → date), dùng để xếp thư mục lưu trữ khi
    # văn bản chưa có ngày ban hành từ Bộ Tư pháp.
    pub_date = _parse_pub_date(
        entry.get("published", "") or entry.get("updated", "")
    )

    return {
        "title": title,
        "tvpl_url": link,
        "tvpl_id": tvpl_id,
        "pub_date": pub_date,
        "field_slug": slug,
        "field_code": field_code,
        "source_tvpl": True,
    }


def filter_business_fields(entries: list[dict]) -> list[dict[str, Any]]:
    """
    Filter RSS entries to only business-related fields,
    and parse each into a normalized dict.
    """
    results = []
    for entry in entries:
        if is_business_item(entry):
            parsed = parse_rss_entry(entry)
            if parsed["tvpl_id"]:
                results.append(parsed)

    logger.info(
        "TVPL RSS filtered: %d business items out of %d total",
        len(results),
        len(entries),
    )
    return results


def scan_rss() -> list[dict[str, Any]]:
    """
    Main entry: fetch RSS → filter business fields → return triggers.
    """
    entries = fetch_rss()
    return filter_business_fields(entries)


# ──────────────────────────────────────────────
# CLI entry point for testing
# ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== TVPL RSS Test: Fetching business document triggers ===\n")
    triggers = scan_rss()
    for i, t in enumerate(triggers[:15], 1):
        print(f"{i}. {t['title'][:80]}")
        print(f"   TVPL ID: {t['tvpl_id']} | Field: {t['field_slug']} (code {t['field_code']})")
        print(f"   URL: {t['tvpl_url'][:80]}...")
        print(f"   Date: {t['pub_date']}")
        print()
    print(f"Tổng: {len(triggers)} văn bản doanh nghiệp từ RSS")
