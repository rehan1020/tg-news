"""Tests for Telegram bot owner command handlers."""

from __future__ import annotations

import pytest

from src.state.manager import BotState
from src.telegram.commands import ALL_SECTORS, NOT_FINANCIAL_ADVICE_NOTICE, handle_command


@pytest.fixture
def clean_state():
    return BotState(
        muted_sectors=[],
        watchlist=[],
        paused=False,
        pending_digest=False,
        digest_queue=[],
    )


def test_help_command(clean_state):
    """Help command returns command catalog and not-financial-advice disclaimer."""
    reply = handle_command("/help", clean_state)
    assert reply is not None
    assert "/status" in reply
    assert "/sectors" in reply
    assert "/mute" in reply
    assert "/unmute" in reply
    assert "/watch" in reply
    assert "/digest" in reply
    assert "/crypto" in reply
    assert "/markets" in reply
    assert "/pause" in reply
    assert "/resume" in reply
    assert NOT_FINANCIAL_ADVICE_NOTICE in reply


def test_status_command(clean_state):
    """Status command reflects current bot state."""
    clean_state.watchlist = ["AAPL", "BTC"]
    clean_state.muted_sectors = ["crypto"]
    clean_state.llm_usage = {"calls_today": 5, "tokens_today": 1200}
    clean_state.digest_queue = [{"headline": "Story 1", "score": 0.5}]

    reply = handle_command(
        "/status",
        clean_state,
        feed_health={"bbc": {"consecutive_failures": 0}},
    )
    assert reply is not None
    assert "Active" in reply
    assert "crypto" in reply
    assert "5 calls" in reply
    assert "1,200 tokens" in reply
    assert "2 terms" in reply or "2" in reply
    assert "1 items" in reply or "1" in reply


def test_sectors_command(clean_state):
    """Sectors command lists all 5 sectors with current status."""
    clean_state.muted_sectors = ["markets"]
    reply = handle_command("/sectors", clean_state)
    assert reply is not None
    for s in ALL_SECTORS:
        assert s in reply
    assert "markets: Muted 🔇" in reply or "markets</b>: Muted 🔇" in reply
    assert "world</b>: Active ✅" in reply


def test_mute_and_unmute_command(clean_state):
    """Mute and unmute successfully toggle sector mute state."""
    # Mute
    reply_mute = handle_command("/mute business", clean_state)
    assert "Muted sector" in reply_mute
    assert "business" in clean_state.muted_sectors

    # Invalid sector mute
    reply_invalid = handle_command("/mute invalid_sector", clean_state)
    assert "Unknown sector" in reply_invalid

    # Unmute
    reply_unmute = handle_command("/unmute business", clean_state)
    assert "Unmuted sector" in reply_unmute
    assert "business" not in clean_state.muted_sectors

    # Unmute when not muted
    reply_unmute_again = handle_command("/unmute business", clean_state)
    assert "not currently muted" in reply_unmute_again


def test_watchlist_commands(clean_state):
    """Watch add, remove, and list correctly update watchlist."""
    # Empty watchlist
    reply_empty = handle_command("/watchlist", clean_state)
    assert "empty" in reply_empty.lower()

    # Add ticker (short ticker auto-uppercased)
    reply_add = handle_command("/watch add tsla", clean_state)
    assert "TSLA" in reply_add
    assert "TSLA" in clean_state.watchlist

    # Add longer keyword (preserved as-is)
    handle_command("/watch add semiconductor industry", clean_state)
    assert "semiconductor industry" in clean_state.watchlist

    # List watchlist
    reply_list = handle_command("/watchlist", clean_state)
    assert "TSLA" in reply_list
    assert "semiconductor industry" in reply_list

    # Remove item (case-insensitive)
    reply_remove = handle_command("/watch remove TsLa", clean_state)
    assert "Removed" in reply_remove
    assert "TSLA" not in clean_state.watchlist


def test_digest_command(clean_state):
    """Digest command triggers pending_digest flag."""
    assert clean_state.pending_digest is False
    reply = handle_command("/digest", clean_state)
    assert "On-demand digest requested" in reply
    assert clean_state.pending_digest is True


def test_crypto_command(clean_state):
    """Crypto command triggers pending_crypto flag with optional filter."""
    assert clean_state.pending_crypto is False
    reply = handle_command("/crypto", clean_state)
    assert "Crypto" in reply
    assert clean_state.pending_crypto is True
    assert clean_state.pending_crypto_filter == ""

    # With filter argument
    clean_state.pending_crypto = False
    reply_filtered = handle_command("/crypto btc", clean_state)
    assert "btc" in reply_filtered
    assert clean_state.pending_crypto is True
    assert clean_state.pending_crypto_filter == "btc"


def test_markets_command(clean_state):
    """Markets command and aliases trigger pending_markets flag with optional filter."""
    assert clean_state.pending_markets is False
    reply = handle_command("/markets", clean_state)
    assert "Business & Market Intelligence Requested" in reply
    assert clean_state.pending_markets is True
    assert clean_state.pending_markets_filter == ""

    # With filter argument
    clean_state.pending_markets = False
    reply_filtered = handle_command("/markets fed rate cut", clean_state)
    assert "fed rate cut" in reply_filtered
    assert clean_state.pending_markets is True
    assert clean_state.pending_markets_filter == "fed rate cut"

    # Aliases
    clean_state.pending_markets = False
    clean_state.pending_markets_filter = ""
    reply_biz = handle_command("/business inflation", clean_state)
    assert "inflation" in reply_biz
    assert clean_state.pending_markets is True
    assert clean_state.pending_markets_filter == "inflation"

    clean_state.pending_markets = False
    handle_command("/finance", clean_state)
    assert clean_state.pending_markets is True

    clean_state.pending_markets = False
    handle_command("/macro", clean_state)
    assert clean_state.pending_markets is True


def test_pause_and_resume_command(clean_state):
    """Pause and resume toggle state.paused flag."""
    assert clean_state.paused is False

    reply_pause = handle_command("/pause", clean_state)
    assert "Paused" in reply_pause
    assert clean_state.paused is True

    reply_resume = handle_command("/resume", clean_state)
    assert "Resumed" in reply_resume
    assert clean_state.paused is False


def test_unknown_command(clean_state):
    """Unknown commands return helpful message with disclaimer."""
    reply = handle_command("/random_command", clean_state)
    assert "Unknown command" in reply
    assert NOT_FINANCIAL_ADVICE_NOTICE in reply


def test_non_command_text(clean_state):
    """Non-command messages return None."""
    assert handle_command("hello there", clean_state) is None
    assert handle_command("breaking news report", clean_state) is None
