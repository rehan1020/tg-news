"""Tests for bot CLI entrypoint."""

from __future__ import annotations

from unittest.mock import patch

from src.bot.__main__ import main


class TestMainEntrypoint:
    def test_main_dry_run_flag(self):
        """CLI main with --dry-run should return 0."""
        with patch("sys.argv", ["bot", "--dry-run"]):
            ret = main()
            assert ret == 0

    def test_main_handles_exception(self):
        """CLI main should catch exceptions and return 1."""
        with (
            patch("sys.argv", ["bot", "--dry-run"]),
            patch("src.bot.__main__.run", side_effect=RuntimeError("test error")),
        ):
            ret = main()
            assert ret == 1

    def test_main_force_digest_flag(self):
        """CLI main with --force-digest should pass flag."""
        with (
            patch("sys.argv", ["bot", "--dry-run", "--force-digest"]),
            patch("src.bot.__main__.run") as mock_run,
        ):
            ret = main()
            assert ret == 0
            mock_run.assert_called_once_with(dry_run=True, force_digest=True)
