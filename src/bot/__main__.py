"""News bot entrypoint — invoked as ``python -m src.bot``."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from src.bot.logger import get_logger, setup_logging
from src.bot.runner import run


def main() -> int:
    """Parse CLI flags, configure logging, and execute the async pipeline."""
    parser = argparse.ArgumentParser(description="Telegram News Bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run full pipeline without sending to Telegram or writing state",
    )
    parser.add_argument(
        "--force-digest",
        action="store_true",
        default=False,
        help="Force compiling and dispatching digest regardless of schedule",
    )
    parser.add_argument(
        "--crypto",
        action="store_true",
        default=False,
        help="Force compiling and dispatching crypto day-trading intelligence report",
    )
    parser.add_argument(
        "--markets",
        action="store_true",
        default=False,
        help="Force compiling and dispatching business & market intelligence report",
    )
    args = parser.parse_args()

    # Also check DRY_RUN, FORCE_DIGEST, FORCE_CRYPTO, and FORCE_MARKETS env vars
    dry_run: bool = args.dry_run or os.environ.get("DRY_RUN", "").lower() in (
        "true",
        "1",
        "yes",
    )
    force_digest: bool = args.force_digest or os.environ.get("FORCE_DIGEST", "").lower() in (
        "true",
        "1",
        "yes",
    )
    force_crypto: bool = args.crypto or os.environ.get("FORCE_CRYPTO", "").lower() in (
        "true",
        "1",
        "yes",
    )
    force_markets: bool = args.markets or os.environ.get("FORCE_MARKETS", "").lower() in (
        "true",
        "1",
        "yes",
    )

    setup_logging()
    logger = get_logger(__name__)
    logger.info(
        "bot starting",
        extra={
            "dry_run": dry_run,
            "force_digest": force_digest,
            "force_crypto": force_crypto,
            "force_markets": force_markets,
        },
    )

    try:
        asyncio.run(
            run(
                dry_run=dry_run,
                force_digest=force_digest,
                force_crypto=force_crypto,
                force_markets=force_markets,
            )
        )
        logger.info("bot finished successfully")
        return 0
    except Exception:
        logger.exception("bot run failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
