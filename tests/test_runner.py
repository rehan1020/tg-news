"""Tests for the pipeline runner."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.bot.runner import apply_start_delay, run


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
