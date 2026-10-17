"""Digest slot scheduling, message formatting, and queue management."""

from __future__ import annotations

import html
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.bot.logger import get_logger
from src.feeds.models import FeedItem
from src.telegram.client import SECTOR_EMOJIS, TelegramClient, format_relative_time

logger = get_logger(__name__)

# Grace window for cron jitter: 45 minutes after the slot time
SLOT_GRACE_WINDOW_SECONDS = 45 * 60


def get_current_local_time(tz_name: str) -> datetime:
    """Get current time in the configured timezone."""
    now_utc = datetime.now(UTC)
    try:
        zone = ZoneInfo(tz_name)
        return now_utc.astimezone(zone)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("invalid timezone configured, defaulting to UTC", extra={"tz": tz_name})
        return now_utc


def check_due_digest_slots(
    local_dt: datetime,
    digest_times: list[str],
    digest_history: dict[str, bool],
) -> str | None:
    """Check if any configured digest slot is due to fire.

    A slot fires on the first run at or after its scheduled time within the grace window,
    and sends at most once per calendar day (tracked via digest_history).

    Args:
        local_dt: Current datetime in the local timezone.
        digest_times: List of "HH:MM" slot times (e.g. ["08:00", "18:00"]).
        digest_history: Dict of previously fired slot keys.

    Returns:
        The slot key (e.g. "2026-10-17_08:00") if due, or None.
    """
    date_str = local_dt.strftime("%Y-%m-%d")

    for slot_time_str in digest_times:
        slot_time_str = slot_time_str.strip()
        if not slot_time_str:
            continue
        try:
            parts = slot_time_str.split(":")
            hour = int(parts[0])
            minute = int(parts[1])
            slot_dt = local_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, IndexError):
            logger.warning("malformed digest time slot", extra={"slot": slot_time_str})
            continue

        slot_key = f"{date_str}_{slot_time_str}"
        if digest_history.get(slot_key):
            # Already sent today
            continue

        diff_seconds = (local_dt - slot_dt).total_seconds()
        # Fire if current time is at or after slot time, within the grace window
        if 0 <= diff_seconds <= SLOT_GRACE_WINDOW_SECONDS:
            return slot_key

    return None


def item_to_digest_dict(
    item: FeedItem,
    cluster_size: int = 1,
    score: float = 0.0,
    summary: str = "",
) -> dict[str, Any]:
    """Convert FeedItem into state-safe digest queue dictionary."""
    return {
        "url": item.canonical_url or item.url,
        "headline": item.title,
        "sector": item.sector.lower(),
        "score": round(score, 3),
        "source_name": item.source_name,
        "cluster_size": cluster_size,
        "published_at": item.published_at,
        "timestamp": time.time(),
        "summary": summary,
    }


def format_digest_messages(
    items: list[dict[str, Any]],
    slot_label: str = "Digest",
) -> list[str]:
    """Format a batch of digest items into one or more Telegram messages (<=4096 chars)."""
    if not items:
        return []

    header = (
        f"📰 <b>{html.escape(slot_label.upper())}</b>\n"
        f"<i>Curated top stories across monitored sectors ({len(items)} items)</i>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    story_blocks: list[str] = [header]

    for itm in items:
        sector_name = itm.get("sector", "world")
        sector_tag = SECTOR_EMOJIS.get(sector_name, f"📰 #{sector_name.upper()}")
        headline = html.escape(itm.get("headline", "Untitled"))
        url = html.escape(itm.get("url", ""), quote=True)
        source = html.escape(itm.get("source_name", "Source"))
        published_at = itm.get("published_at", time.time())
        rel_time = format_relative_time(published_at)
        cluster_size = itm.get("cluster_size", 1)
        summary = itm.get("summary", "")

        block_lines = [
            f"<b>{sector_tag}</b>",
            f"<b>{headline}</b>",
        ]
        if summary:
            block_lines.append(html.escape(summary))

        footer = f"<i>{source} • {rel_time}</i>"
        if cluster_size > 1:
            footer += f" <i>(+{cluster_size - 1} sources)</i>"
        block_lines.append(footer)
        block_lines.append(f'<a href="{url}">Read original</a>')

        story_blocks.append("\n\n".join(block_lines))

    # Join with separator and chunk if necessary
    full_text = "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(story_blocks)
    return TelegramClient._chunk_message(full_text, max_chars=4000)
