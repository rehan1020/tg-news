"""Configuration loader — environment variables + YAML config files.

Secrets come from environment variables; non-secret settings from YAML.
A local override file (``config/sources.local.yml``) is merged on top of
``config/sources.yml`` so operators can customise feeds without touching
the checked-in defaults.

Security invariants:
- Secret fields are **never** logged or included in ``__repr__``.
- ``BotConfig`` is frozen to prevent accidental mutation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.bot.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Project root — two levels up from this file (src/bot/config.py → repo root)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Names of env vars that carry secrets
_SECRET_ENV_VARS: dict[str, str] = {
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_OWNER_CHAT_ID": "telegram_owner_chat_id",
    "STATE_ENCRYPTION_KEY": "state_encryption_key",
    "GEMINI_API_KEY": "gemini_api_key",
    "GROQ_API_KEY": "groq_api_key",
    "FINNHUB_API_KEY": "finnhub_api_key",
    "ALPHAVANTAGE_API_KEY": "alphavantage_api_key",
    "GUARDIAN_API_KEY": "guardian_api_key",
    "NYT_API_KEY": "nyt_api_key",
    "CRYPTOPANIC_API_KEY": "cryptopanic_api_key",
}

# Fields whose values must never appear in logs or repr
_REDACTED_FIELDS: frozenset[str] = frozenset(
    {
        "telegram_bot_token",
        "telegram_owner_chat_id",
        "state_encryption_key",
        "gemini_api_key",
        "groq_api_key",
        "finnhub_api_key",
        "alphavantage_api_key",
        "guardian_api_key",
        "nyt_api_key",
        "cryptopanic_api_key",
    }
)


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


# ---------------------------------------------------------------------------
# BotConfig dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BotConfig:
    """Immutable bot configuration.

    All secret fields default to empty strings so the dataclass can always
    be constructed; validation in :func:`load_config` ensures required
    secrets are present before the pipeline runs.
    """

    # --- Operational settings ---
    max_start_delay_seconds: int = 180
    dry_run: bool = False
    timezone: str = "UTC"

    # --- Scheduling ---
    digest_times: tuple[str, ...] = ("08:00", "18:00")
    quiet_hours: tuple[str, str] | None = None

    # --- Content filtering ---
    watchlist: tuple[str, ...] = ()

    # --- Feed sources (loaded from YAML) ---
    sources: tuple[dict[str, Any], ...] = ()

    # --- Secrets (from environment variables) ---
    telegram_bot_token: str = ""
    telegram_owner_chat_id: str = ""
    state_encryption_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str | None = None
    finnhub_api_key: str | None = None
    alphavantage_api_key: str | None = None
    guardian_api_key: str | None = None
    nyt_api_key: str | None = None
    cryptopanic_api_key: str | None = None

    # --- repr: redact secrets ---

    def __repr__(self) -> str:
        safe_fields: list[str] = []
        for f in self.__dataclass_fields__:
            val = getattr(self, f)
            display = ("'[SET]'" if val else "'[NOT SET]'") if f in _REDACTED_FIELDS else repr(val)
            safe_fields.append(f"{f}={display}")
        return f"BotConfig({', '.join(safe_fields)})"


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return the top-level mapping.

    Returns an empty dict if the file does not exist or is empty.
    """
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Expected YAML mapping at top level in {path}, got {type(data).__name__}"
        )
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base* (override wins).

    Lists are replaced, not concatenated.
    """
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_sources_config() -> dict[str, Any]:
    """Load ``config/sources.yml`` with optional local overrides."""
    base_path = _PROJECT_ROOT / "config" / "sources.yml"
    local_path = _PROJECT_ROOT / "config" / "sources.local.yml"

    base = _load_yaml(base_path)
    local = _load_yaml(local_path)

    if local:
        logger.info("merging local config override", extra={"path": str(local_path)})
        return _deep_merge(base, local)

    return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(dry_run: bool | None = None) -> BotConfig:
    """Build a :class:`BotConfig` from environment + YAML files.

    Raises:
        ConfigError: If any required secret is missing and dry_run is False.
    """
    # 1. Load YAML sources configuration
    yaml_cfg = _load_sources_config()

    # 2. Extract fields from YAML
    yaml_settings: dict[str, Any] = {}

    if "max_start_delay_seconds" in yaml_cfg:
        yaml_settings["max_start_delay_seconds"] = int(yaml_cfg["max_start_delay_seconds"])
    if "MAX_START_DELAY_SECONDS" in os.environ:
        yaml_settings["max_start_delay_seconds"] = int(os.environ["MAX_START_DELAY_SECONDS"])

    if "timezone" in yaml_cfg:
        yaml_settings["timezone"] = str(yaml_cfg["timezone"])
    if "TIMEZONE" in os.environ:
        yaml_settings["timezone"] = os.environ["TIMEZONE"].strip()

    if "digest_times" in yaml_cfg:
        raw_times = yaml_cfg["digest_times"]
        if isinstance(raw_times, list):
            yaml_settings["digest_times"] = tuple(str(t) for t in raw_times)
    if "DIGEST_TIMES" in os.environ:
        yaml_settings["digest_times"] = tuple(
            t.strip() for t in os.environ["DIGEST_TIMES"].split(",") if t.strip()
        )

    if "quiet_hours" in yaml_cfg:
        qh = yaml_cfg["quiet_hours"]
        if isinstance(qh, dict) and "start" in qh and "end" in qh:
            yaml_settings["quiet_hours"] = (str(qh["start"]), str(qh["end"]))
        elif qh is None:
            yaml_settings["quiet_hours"] = None
    if "QUIET_HOURS" in os.environ:
        raw_qh = os.environ["QUIET_HOURS"].strip()
        if "-" in raw_qh:
            parts = raw_qh.split("-", 1)
            yaml_settings["quiet_hours"] = (parts[0].strip(), parts[1].strip())

    if "watchlist" in yaml_cfg:
        raw_watchlist = yaml_cfg["watchlist"]
        if isinstance(raw_watchlist, list):
            yaml_settings["watchlist"] = tuple(str(w) for w in raw_watchlist)
    if "WATCHLIST" in os.environ:
        yaml_settings["watchlist"] = tuple(
            w.strip() for w in os.environ["WATCHLIST"].split(",") if w.strip()
        )

    if "sources" in yaml_cfg:
        raw_sources = yaml_cfg["sources"]
        if isinstance(raw_sources, list):
            yaml_settings["sources"] = tuple(raw_sources)

    # 3. Read secrets from environment
    secrets: dict[str, str] = {}
    for env_var, field_name in _SECRET_ENV_VARS.items():
        raw_val = os.environ.get(env_var, "")
        if raw_val:
            cleaned_val = raw_val.strip().strip("'\"")
            if cleaned_val:
                secrets[field_name] = cleaned_val

    # 4. Check DRY_RUN
    if dry_run is not None:
        yaml_settings["dry_run"] = dry_run
    else:
        dry_run_env = os.environ.get("DRY_RUN", "").lower() in ("true", "1", "yes")
        if dry_run_env:
            yaml_settings["dry_run"] = True

    # 5. Build config
    config = BotConfig(**yaml_settings, **secrets)

    # 6. Validate required secrets
    missing: list[str] = []
    if not config.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not config.telegram_owner_chat_id:
        missing.append("TELEGRAM_OWNER_CHAT_ID")
    if not config.state_encryption_key:
        missing.append("STATE_ENCRYPTION_KEY")

    if missing and not config.dry_run:
        raise ConfigError(
            f"Required environment variable(s) not set: {', '.join(missing)}. "
            "Set these before running, or use --dry-run to skip validation."
        )

    if missing and config.dry_run:
        logger.warning(
            "running in dry-run mode with missing secrets",
            extra={"missing": missing},
        )

    logger.info("configuration loaded", extra={"config": repr(config)})
    return config
