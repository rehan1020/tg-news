"""Owner command handlers for the Telegram bot.

Supported commands:
- /help (includes not-financial-advice notice)
- /status (last run, feed health, LLM budget)
- /sectors
- /mute <sector>
- /unmute <sector>
- /watch add|remove <value>
- /watchlist
- /digest (on-demand digest)
- /pause
- /resume
"""

from __future__ import annotations

import html
import time
from typing import Any

from src.bot.logger import get_logger
from src.state.manager import BotState

logger = get_logger(__name__)

ALL_SECTORS = ("world", "india", "business", "markets", "crypto")

NOT_FINANCIAL_ADVICE_NOTICE = (
    "⚠️ <b>Notice</b>: This bot provides automated news aggregation for informational "
    "purposes only. It does not provide financial, investment, or trading advice. "
    "No warranty of any kind is provided."
)


def handle_command(
    text: str,
    state: BotState,
    feed_health: dict[str, Any] | None = None,
) -> str | None:
    """Parse and execute a Telegram command.

    Args:
        text: Raw text received from owner.
        state: Mutable BotState object.
        feed_health: Optional dict summarizing feed status.

    Returns:
        Formatted HTML response string to send to owner, or None if text is not a command.
    """
    clean_text = text.strip()
    if not clean_text.startswith("/"):
        return None

    # Split command and arguments
    parts = clean_text.split()
    cmd_raw = parts[0].lower()
    # Strip @botname if present (e.g. /help@my_news_bot -> /help)
    cmd = cmd_raw.split("@")[0]
    args = parts[1:]

    logger.info("processing owner command", extra={"command": cmd})

    if cmd == "/help" or cmd == "/start":
        return _handle_help()
    elif cmd == "/status":
        return _handle_status(state, feed_health or {})
    elif cmd == "/sectors":
        return _handle_sectors(state)
    elif cmd == "/mute":
        return _handle_mute(args, state)
    elif cmd == "/unmute":
        return _handle_unmute(args, state)
    elif cmd == "/watch":
        return _handle_watch(args, state)
    elif cmd == "/watchlist":
        return _handle_watchlist(state)
    elif cmd == "/digest":
        return _handle_digest(state)
    elif cmd == "/pause":
        return _handle_pause(state)
    elif cmd == "/resume":
        return _handle_resume(state)
    else:
        return (
            "❓ Unknown command. Type /help to see all available commands.\n\n"
            + NOT_FINANCIAL_ADVICE_NOTICE
        )


def _handle_help() -> str:
    return (
        "🤖 <b>Telegram News Bot Commands</b>\n\n"
        "• /status — Current bot operational status and LLM usage\n"
        "• /sectors — View sectors and their active/muted status\n"
        "• /mute &lt;sector&gt; — Mute news alerts for a sector\n"
        "• /unmute &lt;sector&gt; — Unmute news alerts for a sector\n"
        "• /watchlist — View active watchlist keywords\n"
        "• /watch add &lt;term&gt; — Add a term or ticker to watchlist\n"
        "• /watch remove &lt;term&gt; — Remove a term from watchlist\n"
        "• /digest — Request an immediate on-demand news digest\n"
        "• /pause — Pause delivery of breaking alerts and digests\n"
        "• /resume — Resume news delivery\n"
        "• /help — Show this help message\n\n" + NOT_FINANCIAL_ADVICE_NOTICE
    )


def _handle_status(state: BotState, feed_health: dict[str, Any]) -> str:
    status_str = "⏸️ Paused" if state.paused else "✅ Active"
    llm = state.llm_usage
    calls = llm.get("calls_today", 0)
    tokens = llm.get("tokens_today", 0)

    # Calculate feed stats
    total_feeds = len(state.feed_states)
    failing_feeds = sum(
        1 for f in state.feed_states.values() if f.get("consecutive_failures", 0) >= 3
    )
    healthy_feeds = total_feeds - failing_feeds

    muted = ", ".join(state.muted_sectors) if state.muted_sectors else "None"
    watchlist_count = len(state.watchlist)
    queued_digest_count = len(state.digest_queue)

    diff_seconds = max(0.0, time.time() - state.updated_at)
    minutes_ago = int(diff_seconds // 60)
    last_updated_str = f"{minutes_ago}m ago" if minutes_ago > 0 else "just now"

    feed_line = (
        f"• <b>Feeds Monitored</b>: {total_feeds} "
        f"({healthy_feeds} healthy, {failing_feeds} failing)\n"
    )
    return (
        "📊 <b>Bot Operational Status</b>\n\n"
        f"• <b>Status</b>: {status_str}\n"
        f"• <b>Last Run</b>: {last_updated_str}\n"
        f"{feed_line}"
        f"• <b>LLM Usage Today</b>: {calls} calls ({tokens:,} tokens)\n"
        f"• <b>Muted Sectors</b>: {html.escape(muted)}\n"
        f"• <b>Watchlist Terms</b>: {watchlist_count}\n"
        f"• <b>Queued for Digest</b>: {queued_digest_count} items"
    )


def _handle_sectors(state: BotState) -> str:
    lines = ["🌐 <b>News Sectors</b>\n"]
    for s in ALL_SECTORS:
        if s in state.muted_sectors:
            lines.append(f"• <b>{s}</b>: Muted 🔇")
        else:
            lines.append(f"• <b>{s}</b>: Active ✅")
    lines.append("\n<i>Use /mute &lt;sector&gt; or /unmute &lt;sector&gt; to toggle.</i>")
    return "\n".join(lines)


def _handle_mute(args: list[str], state: BotState) -> str:
    if not args:
        return (
            f"Usage: <code>/mute &lt;sector&gt;</code>\nAvailable sectors: {', '.join(ALL_SECTORS)}"
        )
    sector = args[0].lower().strip()
    if sector not in ALL_SECTORS:
        return (
            f"❌ Unknown sector '<b>{html.escape(sector)}</b>'.\n"
            f"Available sectors: {', '.join(ALL_SECTORS)}"
        )
    if sector not in state.muted_sectors:
        state.muted_sectors.append(sector)
    return f"🔇 Muted sector <b>{html.escape(sector)}</b>. Alerts will be suppressed."


def _handle_unmute(args: list[str], state: BotState) -> str:
    if not args:
        return (
            "Usage: <code>/unmute &lt;sector&gt;</code>\n"
            f"Available sectors: {', '.join(ALL_SECTORS)}"
        )
    sector = args[0].lower().strip()
    if sector in state.muted_sectors:
        state.muted_sectors.remove(sector)
        return f"🔔 Unmuted sector <b>{html.escape(sector)}</b>. Alerts are now active."
    return f"Sector <b>{html.escape(sector)}</b> is not currently muted."


def _handle_watch(args: list[str], state: BotState) -> str:
    if len(args) < 2:
        return (
            "Usage:\n"
            "• <code>/watch add &lt;term&gt;</code>\n"
            "• <code>/watch remove &lt;term&gt;</code>"
        )
    action = args[0].lower()
    term = " ".join(args[1:]).strip()

    if action == "add":
        # Normalize uppercase if short ticker, else preserve
        clean_term = term.upper() if len(term) <= 5 and term.isalnum() else term
        if clean_term not in state.watchlist:
            state.watchlist.append(clean_term)
        return f"⭐ Added '<b>{html.escape(clean_term)}</b>' to watchlist."
    elif action == "remove":
        # Case-insensitive removal
        matching = [t for t in state.watchlist if t.lower() == term.lower()]
        if matching:
            for m in matching:
                state.watchlist.remove(m)
            return f"Removed '<b>{html.escape(matching[0])}</b>' from watchlist."
        return f"Term '<b>{html.escape(term)}</b>' was not found in watchlist."
    else:
        return "Unknown action. Use <code>/watch add</code> or <code>/watch remove</code>."


def _handle_watchlist(state: BotState) -> str:
    if not state.watchlist:
        return (
            "⭐ <b>Watchlist is empty.</b>\n\n"
            "Add terms with <code>/watch add &lt;ticker or keyword&gt;</code>."
        )
    terms_formatted = "\n".join(f"• <code>{html.escape(t)}</code>" for t in state.watchlist)
    return (
        f"⭐ <b>Active Watchlist</b> ({len(state.watchlist)} terms):\n\n"
        f"{terms_formatted}\n\n"
        "<i>Use /watch add or /watch remove to modify.</i>"
    )


def _handle_digest(state: BotState) -> str:
    state.pending_digest = True
    return "📰 On-demand digest requested. Generating and delivering digest..."


def _handle_pause(state: BotState) -> str:
    state.paused = True
    return (
        "⏸️ <b>News Delivery Paused</b>\n\n"
        "Feeds will still be tracked to keep state updated, but no messages "
        "will be sent to Telegram until you send /resume."
    )


def _handle_resume(state: BotState) -> str:
    state.paused = False
    return "▶️ <b>News Delivery Resumed</b>\n\nBreaking alerts and digests will be delivered."
