"""Security tests — verify no secrets can leak."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

from src.bot.logger import get_logger, setup_logging


class TestNoSecretLeakage:
    FAKE_SECRETS = {
        "TELEGRAM_BOT_TOKEN": "9999999999:AAFakeTokenForSecurityTest_abc",
        "TELEGRAM_OWNER_CHAT_ID": "987654321",
        "STATE_ENCRYPTION_KEY": "ZmFrZS1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==",
        "GEMINI_API_KEY": "AIzaSyFakeKeyForSecurityTesting12345",
        "GROQ_API_KEY": "gsk_FakeGroqKeyForSecurityTesting1234567",
    }

    def test_secrets_never_in_log_output(self):
        """No fake secret should appear in log output, no matter how it's logged."""
        with patch.dict(os.environ, self.FAKE_SECRETS, clear=False):
            import io

            stream = io.StringIO()

            setup_logging()
            root = logging.getLogger()
            for handler in root.handlers:
                handler.stream = stream

            logger = get_logger("security.test")

            # Try various ways secrets might leak
            for key, value in self.FAKE_SECRETS.items():
                logger.info(f"Config {key}={value}")
                logger.info("Token: %s", value)
                logger.info("Data: %(token)s", {"token": value})
                logger.warning(f"Error connecting with {value}")

            output = stream.getvalue()
            for value in self.FAKE_SECRETS.values():
                if len(value) >= 8:  # Only check values long enough to be redacted
                    assert value not in output, f"Secret leaked in logs: {value[:8]}..."

    def test_url_secrets_redacted_in_logs(self):
        """API keys in URL query params must be redacted."""
        with patch.dict(os.environ, self.FAKE_SECRETS, clear=False):
            import io

            stream = io.StringIO()

            setup_logging()
            root = logging.getLogger()
            for handler in root.handlers:
                handler.stream = stream

            logger = get_logger("security.url")
            logger.info("Request to https://api.example.com?api_key=SUPERSECRET123&v=2")
            logger.info("Guardian: https://content.guardianapis.com/search?api-key=GUARDIANKEY1")

            output = stream.getvalue()
            assert "SUPERSECRET123" not in output
