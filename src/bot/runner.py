"""Pipeline orchestrator — runs each step in sequence."""

from __future__ import annotations

import asyncio
import random

from src.bot.config import BotConfig, load_config
from src.bot.logger import get_logger
from src.extract.extractor import ArticleExtractor
from src.feeds.fetcher import FeedFetcher
from src.llm.orchestrator import LLMOrchestrator
from src.pipeline.clustering import cluster_items
from src.pipeline.dedupe import deduplicate_items
from src.pipeline.scoring import ScoringEngine
from src.state.manager import StateManager
from src.telegram.client import TelegramClient, format_headline_message

logger = get_logger(__name__)


async def apply_start_delay(max_delay_seconds: int) -> None:
    """Random start delay to desynchronize forks hitting the same feeds."""
    if max_delay_seconds <= 0:
        return
    delay = random.uniform(0, max_delay_seconds)
    logger.info("start delay applied", extra={"delay_seconds": round(delay, 1)})
    await asyncio.sleep(delay)


async def run(*, dry_run: bool = False, config_override: BotConfig | None = None) -> None:
    """Execute the full bot pipeline."""
    config = config_override or load_config(dry_run=dry_run)

    # Step 1: Random start delay
    if not dry_run:
        await apply_start_delay(config.max_start_delay_seconds)
    else:
        logger.info("skipping start delay in dry-run mode")

    # Step 2: Load and decrypt state
    state_manager = StateManager(
        encryption_key=config.state_encryption_key,
        dry_run=dry_run,
    )
    state = state_manager.load_state()

    # Step 3: Telegram client and owner updates
    telegram = TelegramClient(
        bot_token=config.telegram_bot_token,
        owner_chat_id=config.telegram_owner_chat_id,
        dry_run=dry_run,
    )
    updates = await telegram.get_owner_updates(state)
    logger.info("telegram updates received", extra={"count": len(updates)})

    # Step 4: Poll feeds (conditional GET, health tracking)
    fetcher = FeedFetcher()
    raw_items = await fetcher.fetch_all(config.sources, state)
    logger.info("feed polling completed", extra={"raw_items_count": len(raw_items)})

    # Step 5: Normalize, canonicalize URLs, dedupe
    unique_items, dropped_count = deduplicate_items(raw_items, state)
    logger.info(
        "deduplication completed",
        extra={"unique_count": len(unique_items), "dropped_count": dropped_count},
    )

    # Step 6: Cluster, score, and route
    clusters = cluster_items(unique_items)
    scoring_engine = ScoringEngine()
    breaking, digest, discarded = scoring_engine.route_clusters(
        clusters=clusters,
        state=state,
        quiet_hours=config.quiet_hours,
        tz_name=config.timezone,
    )

    if dry_run:
        # Display score breakdowns in dry-run mode
        for sc in breaking:
            logger.info(
                "dry-run score breakdown (breaking)",
                extra={
                    "sector": sc.cluster.primary_item.sector,
                    "score": sc.score.total,
                    "trust": sc.score.trust,
                    "recency": sc.score.recency,
                    "cluster_boost": sc.score.cluster_boost,
                    "watchlist_boost": sc.score.watchlist_boost,
                    "breaking_boost": sc.score.breaking_boost,
                    "penalties": sc.score.penalties,
                },
            )

    # Step 7: Initialize extractor and LLM orchestrator
    extractor = ArticleExtractor()
    llm_orchestrator = LLMOrchestrator(
        gemini_api_key=config.gemini_api_key,
        groq_api_key=config.groq_api_key,
    )

    # Step 8 & 9: Extract, summarize, and send breaking items immediately
    sent_count = 0
    if not state.paused:
        for sc in breaking:
            item = sc.cluster.primary_item

            # Extract full text or fallback to snippet
            article_text, is_extracted_fallback = await extractor.extract_text(
                item.url,
                extract_mode="full",
                snippet_fallback=item.summary_raw,
            )

            # Summarize via LLM (or degrade to snippet on budget/failure)
            summary_bullets, is_rss = await llm_orchestrator.summarize_story(
                title=item.title,
                text=article_text,
                snippet=item.summary_raw,
                state=state,
            )

            is_rss_only = is_extracted_fallback or is_rss
            message_text = format_headline_message(
                item=item,
                bullets=summary_bullets,
                cluster_size=sc.cluster.size,
                is_rss_only=is_rss_only,
            )
            success = await telegram.send_message(message_text)
            if success:
                sent_count += 1
    else:
        logger.info("bot is paused; skipping message dispatch")

    # Step 10: Encrypt and persist state
    state_manager.save_state(state)

    logger.info(
        "pipeline complete",
        extra={
            "dry_run": dry_run,
            "raw_items": len(raw_items),
            "unique_items": len(unique_items),
            "sent_messages": sent_count,
        },
    )
