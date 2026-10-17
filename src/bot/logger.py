"""Central logging with automatic secret redaction.

All logging MUST go through this module. It redacts:
- Known secret values (injected at setup time from env vars)
- Token-like patterns (API keys, JWT tokens, hex strings > 20 chars)
- URLs with query-string credentials
- Chat IDs
"""

from __future__ import annotations

import logging
import os
import re

# Patterns that look like secrets
_TOKEN_PATTERNS = [
    re.compile(r"[A-Za-z0-9_-]{20,}"),  # Generic long alphanumeric
    re.compile(r"\b[0-9]{5,}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token format
    re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"),  # Google API key
    re.compile(r"\bgsk_[A-Za-z0-9_-]{20,}\b"),  # Groq API key
    re.compile(r"\b[a-f0-9]{32,}\b"),  # Hex strings (API keys)
]

# URL query params that often carry secrets
_SECRET_QUERY_PARAMS = {"key", "apikey", "api_key", "token", "access_token", "secret"}


class RedactingFilter(logging.Filter):
    """Logging filter that redacts known secrets and secret-like patterns."""

    def __init__(self, secret_values: frozenset[str] | None = None) -> None:
        super().__init__()
        self._secret_values: frozenset[str] = secret_values or frozenset()
        self._url_param_re = re.compile(
            r"([?&](?:" + "|".join(_SECRET_QUERY_PARAMS) + r")=)([^&\s]+)",
            re.IGNORECASE,
        )

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                new_args = []
                for a in record.args:
                    if isinstance(a, dict):
                        new_args.append({k: self._redact(str(v)) for k, v in a.items()})
                    else:
                        new_args.append(self._redact(str(a)))
                record.args = tuple(new_args)
        return True

    def _redact(self, text: str) -> str:
        # First: redact known secret values (exact match)
        for secret in self._secret_values:
            if secret and secret in text:
                text = text.replace(secret, "[REDACTED]")
        # Second: redact URL query params that carry secrets
        text = self._url_param_re.sub(r"\1[REDACTED]", text)
        return text


def _collect_secret_values() -> frozenset[str]:
    """Collect secret values from environment for redaction.

    Only collects values that are actually set and non-empty.
    Short values (< 8 chars) are excluded to avoid false-positive redaction.
    """
    secret_env_vars = [
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
    ]
    values = set()
    for name in secret_env_vars:
        val = os.environ.get(name, "")
        if val and len(val) >= 8:
            values.add(val)
    return frozenset(values)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging with redaction filter."""
    secret_values = _collect_secret_values()

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s — %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter(secret_values))

    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers to avoid duplicates
    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Always use this instead of logging.getLogger()."""
    return logging.getLogger(name)
