"""Integration test: full dry-run pipeline."""

from __future__ import annotations

import pytest

from src.bot.runner import run


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_completes(self, mock_env):
        """Dry-run mode should complete without errors."""
        await run(dry_run=True)

    @pytest.mark.asyncio
    async def test_dry_run_no_secret_in_output(self, mock_env, capsys):
        """Dry-run output must not contain any secret values."""
        from src.bot.logger import setup_logging

        setup_logging()
        await run(dry_run=True)
        captured = capsys.readouterr()
        for val in mock_env.values():
            assert val not in captured.out
            assert val not in captured.err
