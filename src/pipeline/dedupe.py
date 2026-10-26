"""Deduplication engine — URL hash and SimHash against seen-store and intra-batch."""

from __future__ import annotations

import time

from src.bot.logger import get_logger
from src.feeds.models import FeedItem
from src.pipeline.simhash import is_near_duplicate
from src.pipeline.similarity import is_story_seen
from src.state.manager import BotState

logger = get_logger(__name__)


def deduplicate_items(
    items: list[FeedItem],
    state: BotState,
    max_simhash_distance: int = 14,
) -> tuple[list[FeedItem], int]:
    """Filter out items already seen in state or near-duplicates within the batch.

    Returns:
        (unique_items, dropped_count)
    """
    unique_items: list[FeedItem] = []
    dropped_count = 0
    now = time.time()

    # Track new items added in this run for intra-batch deduplication
    batch_url_hashes: set[str] = set()
    batch_simhashes: list[int] = []

    for item in items:
        # 1. Exact canonical URL hash check in persistent state
        if item.id in state.seen_hashes:
            dropped_count += 1
            continue

        # 2. Exact canonical URL hash check within current batch
        if item.id in batch_url_hashes:
            dropped_count += 1
            continue

        # 3. Check if this story was already covered in a previous run
        is_dup = False
        if is_story_seen(item.title, state.seen_story_hashes):
            is_dup = True

        # 4. Near-duplicate title check against persistent state
        if not is_dup and item.simhash:
            for seen_simhash_str in state.seen_simhashes:
                try:
                    seen_simhash = int(seen_simhash_str)
                    if is_near_duplicate(
                        item.simhash, seen_simhash, max_distance=max_simhash_distance
                    ):
                        is_dup = True
                        break
                except ValueError:
                    continue

        # 5. Near-duplicate title check within current batch for same source
        if not is_dup and item.simhash:
            for b_simhash in batch_simhashes:
                if is_near_duplicate(item.simhash, b_simhash, max_distance=max_simhash_distance):
                    is_dup = True
                    break

        if is_dup:
            dropped_count += 1
            continue

        # Item is unique
        unique_items.append(item)
        batch_url_hashes.add(item.id)
        if item.simhash:
            batch_simhashes.append(item.simhash)

    # Mark unique items as seen in state
    for item in unique_items:
        state.seen_hashes[item.id] = now
        if item.simhash:
            state.seen_simhashes[str(item.simhash)] = now

    logger.info(
        "deduplication finished",
        extra={
            "input_count": len(items),
            "unique_count": len(unique_items),
            "dropped_count": dropped_count,
        },
    )
    return unique_items, dropped_count
