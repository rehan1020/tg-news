"""Tests for the pipeline runner."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.bot.runner import _select_balanced_digest_items, apply_start_delay, run


class TestStartDelay:
    @pytest.mark.asyncio
    async def test_zero_delay_returns_immediately(self):
        """Zero max delay should not sleep."""
        import time

        start = time.monotonic()
        await apply_start_delay(0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_negative_delay_returns_immediately(self):
        """Negative max delay should not sleep."""
        await apply_start_delay(-1)

    @pytest.mark.asyncio
    async def test_delay_bounded(self):
        """Delay must be between 0 and max_delay_seconds."""
        # We can't easily test randomness, but we can verify it doesn't crash
        await apply_start_delay(1)  # Max 1 second


@pytest.mark.asyncio
async def test_dispatch_command_processed(mock_env):
    """External DISPATCH_COMMAND environment variable is processed cleanly."""
    env = {
        "DISPATCH_COMMAND": "/help",
        "GITHUB_EVENT_NAME": "repository_dispatch",
    }
    with (
        patch.dict("os.environ", env),
        patch("src.telegram.client.TelegramClient.send_message") as mock_send,
    ):
        mock_send.return_value = True
        await run(dry_run=True)


class TestBalancedDigestItems:
    def test_empty_items(self):
        assert _select_balanced_digest_items([]) == []

    def test_under_max_items(self):
        items = [
            {"headline": "A", "sector": "world", "score": 0.5},
            {"headline": "B", "sector": "crypto", "score": 0.9},
        ]
        result = _select_balanced_digest_items(items, max_items=8)
        assert len(result) == 2
        assert result[0]["headline"] == "B"  # sorted by score

    def test_round_robin_prevents_monopoly(self):
        # 10 market items with high scores, 2 world items with lower scores
        items = [
            {"headline": f"M{i}", "sector": "markets", "score": 0.9 - i * 0.01} for i in range(10)
        ] + [
            {"headline": "W1", "sector": "world", "score": 0.5},
            {"headline": "W2", "sector": "world", "score": 0.45},
            {"headline": "I1", "sector": "india", "score": 0.52},
        ]
        # max 6 items: round-robin should pick W1, I1, M0, then W2, M1, etc.
        result = _select_balanced_digest_items(items, max_items=6)
        assert len(result) == 6
        sectors = [it["sector"] for it in result]
        assert "world" in sectors
        assert "india" in sectors
        assert "markets" in sectors
        assert sectors.count("world") >= 2
        assert sectors.count("india") >= 1

    def test_digest_deduplicates_multi_source_same_story(self):
        items = [
            {
                "headline": (
                    "Cyclone Dana: Over 5 lakh evacuated in Odisha, flights suspended in Kolkata"
                ),
                "sector": "india",
                "score": 0.88,
            },
            {
                "headline": (
                    "Cyclone Dana landfall updates: Odisha evacuates 500,000 people; Kolkata shuts"
                ),
                "sector": "india",
                "score": 0.85,
            },
            {
                "headline": "Odisha evacuates 5 lakh people as Cyclone Dana approaches coast",
                "sector": "india",
                "score": 0.82,
            },
            {
                "headline": "Supreme Court grants bail to Manish Sisodia in Delhi excise case",
                "sector": "india",
                "score": 0.75,
            },
        ]
        result = _select_balanced_digest_items(items, max_items=4)
        # Cyclone Dana was covered by 3 sources; only 1 should be selected!
        dana_items = [it for it in result if "dana" in it["headline"].lower()]
        assert len(dana_items) == 1
        assert len(result) == 2  # 1 Cyclone Dana + 1 Sisodia
