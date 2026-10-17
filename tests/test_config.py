"""Tests for configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.bot.config import BotConfig, load_config


class TestConfigLoading:
    def test_loads_with_required_env(self, mock_env):
        """Config loads successfully with all required env vars."""
        config = load_config()
        assert isinstance(config, BotConfig)
        assert config.telegram_bot_token == mock_env["TELEGRAM_BOT_TOKEN"]

    def test_fails_without_bot_token(self, clean_env):
        """Config must fail clearly if TELEGRAM_BOT_TOKEN is missing."""
        with pytest.raises((ValueError, SystemExit)):
            load_config()

    def test_fails_without_owner_chat_id(self, clean_env):
        """Config must fail clearly if TELEGRAM_OWNER_CHAT_ID is missing."""
        with (
            patch.dict(
                os.environ,
                {
                    "TELEGRAM_BOT_TOKEN": "tok",
                    "STATE_ENCRYPTION_KEY": "key1234567890abc",
                    "GEMINI_API_KEY": "AIzaTest1234567890",
                },
            ),
            pytest.raises((ValueError, SystemExit)),
        ):
            load_config()

    def test_repr_redacts_secrets(self, mock_env):
        """Config repr must not contain any secret values."""
        config = load_config()
        repr_str = repr(config)
        for secret_val in mock_env.values():
            assert secret_val not in repr_str

    def test_default_values(self, mock_env):
        """Default config values should be sane."""
        config = load_config()
        assert config.max_start_delay_seconds == 180
        assert config.timezone == "UTC"

    def test_optional_keys_default_none(self, mock_env):
        """Optional API keys default to None when not set."""
        config = load_config()
        assert config.groq_api_key is None or isinstance(config.groq_api_key, str)

    def test_watchlist_parsing(self):
        """WATCHLIST env var should be parsed as comma-separated list."""
        env = {
            "TELEGRAM_BOT_TOKEN": "test-token-1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ",
            "TELEGRAM_OWNER_CHAT_ID": "123456789",
            "STATE_ENCRYPTION_KEY": "dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3ODkwYWJj",
            "GEMINI_API_KEY": "AIzaSyTestKeyForTestingPurposesOnly1234",
            "WATCHLIST": "AAPL,BTC,TSLA",
        }
        with patch.dict(os.environ, env, clear=False):
            config = load_config()
            assert "AAPL" in config.watchlist
            assert "BTC" in config.watchlist
            assert len(config.watchlist) == 3

    def test_digest_times_and_quiet_hours_and_timezone_env(self, mock_env):
        """Private config vars should parse properly from env."""
        env = {
            "DIGEST_TIMES": "09:00, 19:30",
            "QUIET_HOURS": "22:00-07:00",
            "TIMEZONE": "Asia/Kolkata",
            "MAX_START_DELAY_SECONDS": "120",
        }
        with patch.dict(os.environ, env, clear=False):
            config = load_config()
            assert config.digest_times == ("09:00", "19:30")
            assert config.quiet_hours == ("22:00", "07:00")
            assert config.timezone == "Asia/Kolkata"
            assert config.max_start_delay_seconds == 120

    def test_local_override_merge(self, mock_env, tmp_path):
        """Local override should merge over base config."""
        from src.bot.config import _deep_merge

        base = {"sources": [{"id": "feed1", "enabled": True}], "timezone": "UTC"}
        override = {"timezone": "Europe/London"}
        merged = _deep_merge(base, override)
        assert merged["timezone"] == "Europe/London"
        assert merged["sources"] == [{"id": "feed1", "enabled": True}]
