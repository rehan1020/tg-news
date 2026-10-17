"""Telegram Bot API client with owner lock, rate limiting, and HTML formatting."""

from __future__ import annotations

import asyncio
import contextlib
import html
import time
from typing import Any

import httpx

from src.bot.logger import get_logger
from src.feeds.models import FeedItem
from src.state.manager import BotState

logger = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096
SEND_INTERVAL_SECONDS = 1.05  # Enforce <= 1 msg/sec limit

SECTOR_EMOJIS = {
    "world": "🌐 #WORLD",
    "india": "🇮🇳 #INDIA",
    "business": "💼 #BUSINESS",
    "markets": "📊 #MARKETS",
    "crypto": "⚡ #CRYPTO",
}


def format_relative_time(published_at: float) -> str:
    """Format timestamp into human-readable relative string."""
    diff = max(0.0, time.time() - published_at)
    minutes = int(diff // 60)
    hours = int(minutes // 60)
    if hours >= 24:
        days = hours // 24
        return f"{days}d ago"
    if hours > 0:
        return f"{hours}h ago"
    if minutes > 0:
        return f"{minutes}m ago"
    return "just now"


def format_headline_message(
    item: FeedItem,
    bullets: str = "",
    cluster_size: int = 1,
    is_rss_only: bool = False,
) -> str:
    """Format a single news item as clean Telegram HTML."""
    sector_tag = SECTOR_EMOJIS.get(item.sector.lower(), f"📰 #{item.sector.upper()}")
    escaped_title = html.escape(item.title)
    escaped_source = html.escape(item.source_name)
    escaped_url = html.escape(item.canonical_url or item.url, quote=True)
    rel_time = format_relative_time(item.published_at)

    lines = [
        f"<b>{sector_tag}</b>",
        f"<b>{escaped_title}</b>",
    ]

    if bullets:
        escaped_bullets = html.escape(bullets)
        lines.append(escaped_bullets)

    footer = f"<i>{escaped_source} • {rel_time}</i>"
    if cluster_size > 1:
        footer += f" <i>(+{cluster_size - 1} other sources)</i>"
    if is_rss_only:
        footer += " <i>[RSS snippet]</i>"
    lines.append(footer)

    lines.append(f'<a href="{escaped_url}">Read original</a>')
    return "\n\n".join(lines)


class TelegramClient:
    """Telegram client enforcing single-owner security lock and outbound rate limiting."""

    def __init__(
        self,
        bot_token: str,
        owner_chat_id: str,
        *,
        dry_run: bool = False,
        api_base: str = TELEGRAM_API_BASE,
    ) -> None:
        self._token = bot_token
        self._owner_chat_id = str(owner_chat_id).strip()
        self._dry_run = dry_run
        self._api_base = f"{api_base}/bot{bot_token}"
        self._last_send_time: float = 0.0

    async def _rate_limit(self) -> None:
        """Ensure outbound rate limit of max 1 message per second."""
        now = time.monotonic()
        elapsed = now - self._last_send_time
        if elapsed < SEND_INTERVAL_SECONDS:
            await asyncio.sleep(SEND_INTERVAL_SECONDS - elapsed)
        self._last_send_time = time.monotonic()

    async def send_message(self, text: str, disable_preview: bool = False) -> bool:
        """Send a message to the owner chat ID. Ignores other chats."""
        if not text.strip():
            return True

        if self._dry_run:
            logger.info(
                "telegram send_message (dry-run)",
                extra={"length": len(text), "preview": text[:60]},
            )
            return True

        await self._rate_limit()

        # Split message if it exceeds Telegram's 4096 character limit
        chunks = self._chunk_message(text, MAX_MESSAGE_LENGTH)
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                url = f"{self._api_base}/sendMessage"
                payload = {
                    "chat_id": self._owner_chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": disable_preview,
                }

                retries = 3
                while retries > 0:
                    try:
                        resp = await client.post(url, json=payload)
                        if resp.status_code == 200:
                            break
                        if resp.status_code == 429:
                            # Honor rate limit retry_after
                            retry_after = 5.0
                            with contextlib.suppress(Exception):
                                raw_retry = resp.json().get("parameters", {}).get("retry_after", 5)
                                retry_after = float(raw_retry)
                            logger.warning(
                                "telegram 429 rate limit",
                                extra={"retry_after": retry_after},
                            )
                            await asyncio.sleep(retry_after)
                            retries -= 1
                            continue
                        logger.warning(
                            "telegram send failed",
                            extra={"status": resp.status_code},
                        )
                        return False
                    except Exception as e:
                        logger.warning("telegram network exception", extra={"error": str(e)})
                        retries -= 1
                        await asyncio.sleep(1.0)

        return True

    async def get_owner_updates(self, state: BotState) -> list[dict[str, Any]]:
        """Poll getUpdates for new messages from the owner ONLY.

        Silently drops and ignores any updates originating from non-owner IDs.
        """
        if self._dry_run or not self._token:
            return []

        url = f"{self._api_base}/getUpdates"
        params = {
            "offset": state.telegram_update_offset,
            "limit": 20,
            "timeout": 0,
        }

        owner_updates: list[dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    logger.warning(
                        "getUpdates returned non-200", extra={"status": resp.status_code}
                    )
                    return []

                data = resp.json()
                if not data.get("ok"):
                    return []

                updates = data.get("result", [])
                max_update_id = state.telegram_update_offset

                for upd in updates:
                    upd_id = upd.get("update_id", 0)
                    if upd_id >= max_update_id:
                        max_update_id = upd_id + 1

                    msg = upd.get("message") or upd.get("channel_post")
                    if not msg:
                        continue

                    # Strict owner verification
                    chat = msg.get("chat", {})
                    from_user = msg.get("from", {})
                    chat_id = str(chat.get("id", ""))
                    from_id = str(from_user.get("id", ""))

                    if chat_id == self._owner_chat_id or from_id == self._owner_chat_id:
                        owner_updates.append(upd)
                    else:
                        # Silently ignore non-owner updates
                        logger.info("silently dropped non-owner telegram update")

                state.telegram_update_offset = max_update_id

        except Exception as e:
            logger.warning("failed to fetch telegram updates", extra={"error": str(e)})

        return owner_updates

    @staticmethod
    def _chunk_message(text: str, max_chars: int = MAX_MESSAGE_LENGTH) -> list[str]:
        """Split text into pieces smaller than max_chars on double newline or newline boundaries."""
        if len(text) <= max_chars:
            return [text]

        chunks: list[str] = []
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for p in paragraphs:
            if not current_chunk:
                current_chunk = p
            elif len(current_chunk) + 2 + len(p) <= max_chars:
                current_chunk = f"{current_chunk}\n\n{p}"
            else:
                chunks.append(current_chunk)
                current_chunk = p

        if current_chunk:
            chunks.append(current_chunk)

        return chunks
