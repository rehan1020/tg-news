"""Shared test fixtures."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Minimal required env vars for config loading
_TEST_ENV = {
    "TELEGRAM_BOT_TOKEN": "test-token-1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ",
    "TELEGRAM_OWNER_CHAT_ID": "123456789",
    "STATE_ENCRYPTION_KEY": "J1DsszMlfX0HxBJwd91qMYH6GfkQBfwbm6lAv_sVJmI=",
    "GEMINI_API_KEY": "AIzaSyTestKeyForTestingPurposesOnly1234",
}


@pytest.fixture
def mock_env():
    """Provide minimal test environment variables."""
    with patch.dict(os.environ, _TEST_ENV, clear=False):
        yield _TEST_ENV


@pytest.fixture
def clean_env():
    """Provide a clean environment with no secrets set."""
    secret_vars = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OWNER_CHAT_ID",
        "STATE_ENCRYPTION_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "FINNHUB_API_KEY",
        "ALPHAVANTAGE_API_KEY",
        "GUARDIAN_API_KEY",
        "NYT_API_KEY",
        "CRYPTOPANIC_API_KEY",
        "WATCHLIST",
        "DIGEST_TIMES",
        "QUIET_HOURS",
        "TIMEZONE",
    ]
    env_backup = {k: os.environ.pop(k, None) for k in secret_vars}
    yield
    for k, v in env_backup.items():
        if v is not None:
            os.environ[k] = v
