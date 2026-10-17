"""Pipeline orchestrator — runs each step in sequence."""

from __future__ import annotations

import asyncio
import random

from src.bot.config import load_config
from src.bot.logger import get_logger

logger = get_logger(__name__)


async def apply_start_delay(max_delay_seconds: int) -> None:
    """Random start delay to desynchronize forks hitting the same feeds."""
    if max_delay_seconds <= 0:
        return
    delay = random.uniform(0, max_delay_seconds)
    logger.info("start delay", extra={"delay_seconds": round(delay, 1)})
    await asyncio.sleep(delay)


async def run(*, dry_run: bool = False) -> None:
    """Execute the full bot pipeline.

    Phase 0: loads config, applies start delay, runs empty pipeline.
    Subsequent phases add steps incrementally.
    """
    config = load_config(dry_run=dry_run)

    # Step 1: Random start delay
    if not dry_run:
        await apply_start_delay(config.max_start_delay_seconds)
    else:
        logger.info("skipping start delay in dry-run mode")

    # Step 2: Load and decrypt state (Phase 1)
    logger.info("step: load state (stub)")

    # Step 3: Read Telegram updates (Phase 1)
    logger.info("step: read telegram updates (stub)")

    # Step 4: Poll feeds (Phase 1)
    logger.info("step: poll feeds (stub)")

    # Step 5: Normalize, canonicalize, dedupe (Phase 1)
    logger.info("step: dedupe (stub)")

    # Step 6: Score and route (Phase 2)
    logger.info("step: score and route (stub)")

    # Step 7: Extract full text (Phase 3)
    logger.info("step: extract (stub)")

    # Step 8: Summarize via LLM (Phase 3)
    logger.info("step: summarize (stub)")

    # Step 9: Send messages (Phase 1+)
    logger.info("step: send messages (stub)")

    # Step 10: Save state (Phase 1)
    logger.info("step: save state (stub)")

    logger.info(
        "pipeline complete",
        extra={
            "dry_run": dry_run,
            "steps_completed": 0,
            "items_processed": 0,
        },
    )
