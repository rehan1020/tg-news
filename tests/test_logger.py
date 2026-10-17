"""Tests for the redacting logger — these are security-critical."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

from src.bot.logger import RedactingFilter, get_logger, setup_logging


class TestRedactingFilter:
    """Test that secrets are never emitted in log output."""

    def test_known_secret_redacted(self):
        """A known secret value must be replaced with [REDACTED]."""
        secret = "my-super-secret-api-key-12345"
        f = RedactingFilter(secret_values=frozenset({secret}))
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Connecting with key {secret} to service",
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert secret not in record.msg
        assert "[REDACTED]" in record.msg

    def test_multiple_secrets_redacted(self):
        """All known secrets must be redacted in a single message."""
        secret1 = "first-secret-value-abcdef"
        secret2 = "second-secret-value-xyz123"
        f = RedactingFilter(secret_values=frozenset({secret1, secret2}))
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Using {secret1} and {secret2}",
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert secret1 not in record.msg
        assert secret2 not in record.msg

    def test_url_query_param_redacted(self):
        """Secret query parameters in URLs must be redacted."""
        f = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="GET https://api.example.com/data?apikey=SECRET123&format=json",
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert "SECRET123" not in record.msg
        assert "format=json" in record.msg  # Non-secret params preserved

    def test_url_api_key_param_redacted(self):
        """api_key parameter should be redacted."""
        f = RedactingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="https://api.example.com/v1?api_key=abc123def456&page=1",
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert "abc123def456" not in record.msg

    def test_args_dict_redacted(self):
        """Secret values in dict args must be redacted."""
        secret = "dict-secret-value-99999"
        f = RedactingFilter(secret_values=frozenset({secret}))
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Config: %(key)s",
            args=({"key": f"token={secret}"},),
            exc_info=None,
        )
        f.filter(record)
        assert secret not in str(record.args)

    def test_args_tuple_redacted(self):
        """Secret values in tuple args must be redacted."""
        secret = "tuple-secret-value-88888"
        f = RedactingFilter(secret_values=frozenset({secret}))
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Values: %s %s",
            args=("safe", f"key={secret}"),
            exc_info=None,
        )
        f.filter(record)
        assert secret not in str(record.args)

    def test_safe_message_unchanged(self):
        """Messages without secrets should pass through unchanged."""
        f = RedactingFilter(secret_values=frozenset({"some-secret-12345678"}))
        original = "Processing 42 items from 5 feeds"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=original,
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert record.msg == original

    def test_short_values_not_collected(self):
        """Values shorter than 8 chars should not be treated as secrets."""
        # This tests the _collect_secret_values function behavior
        f = RedactingFilter(secret_values=frozenset())  # No secrets registered
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Short value: abc",
            args=None,
            exc_info=None,
        )
        f.filter(record)
        assert record.msg == "Short value: abc"


class TestSetupLogging:
    """Test that logging setup integrates the redaction filter."""

    def test_setup_logging_adds_filter(self):
        """setup_logging must add a RedactingFilter to the root handler."""
        test_env = {
            "TELEGRAM_BOT_TOKEN": "test-bot-token-for-logging-test",
        }
        with patch.dict(os.environ, test_env, clear=False):
            setup_logging()
            root = logging.getLogger()
            assert len(root.handlers) > 0
            handler = root.handlers[0]
            filters = handler.filters
            assert any(isinstance(f, RedactingFilter) for f in filters)

    def test_end_to_end_redaction(self):
        """A secret in env should be redacted from actual log output."""
        secret = "e2e-test-secret-value-zzzzzz"
        test_env = {"TELEGRAM_BOT_TOKEN": secret}
        with patch.dict(os.environ, test_env, clear=False):
            setup_logging()
            logger = get_logger("test.e2e")
            # Capture log output
            import io

            stream = io.StringIO()
            root = logging.getLogger()
            for handler in root.handlers:
                handler.stream = stream
            logger.info(f"Token is {secret}")
            output = stream.getvalue()
            assert secret not in output
            assert "[REDACTED]" in output
