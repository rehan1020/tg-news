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
    args = parser.parse_args()

    # Also check DRY_RUN and FORCE_DIGEST env vars (for workflow dispatch)
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

    setup_logging()
    logger = get_logger(__name__)
    logger.info("bot starting", extra={"dry_run": dry_run, "force_digest": force_digest})

    try:
        asyncio.run(run(dry_run=dry_run, force_digest=force_digest))
        logger.info("bot finished successfully")
        return 0
    except Exception:
        logger.exception("bot run failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
