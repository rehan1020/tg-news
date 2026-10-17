"""Pipeline orchestrator — runs each step in sequence."""

from __future__ import annotations

import asyncio
import html
import os
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
from src.telegram.commands import handle_command
from src.telegram.digest import (
    check_due_digest_slots,
    format_digest_messages,
    get_current_local_time,
    item_to_digest_dict,
)

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

    # Step 1: Random start delay (only apply on scheduled cron runs, skip on manual dispatch)
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if not dry_run and not is_manual:
        await apply_start_delay(config.max_start_delay_seconds)
    else:
        logger.info("skipping start delay", extra={"dry_run": dry_run, "manual": is_manual})

    # Step 2: Load and decrypt state
    state_manager = StateManager(
        encryption_key=config.state_encryption_key,
        dry_run=dry_run,
    )
    state = state_manager.load_state()

    # Seed state watchlist from config if empty
    if not state.watchlist and config.watchlist:
        state.watchlist = list(config.watchlist)

    # Step 3: Telegram client and owner updates / commands
    telegram = TelegramClient(
        bot_token=config.telegram_bot_token,
        owner_chat_id=config.telegram_owner_chat_id,
        dry_run=dry_run,
    )
    updates = await telegram.get_owner_updates(state)
    logger.info("telegram updates received", extra={"count": len(updates)})

    on_demand_requested = False
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        text = msg.get("text", "")
        reply = handle_command(text, state, feed_health=state.feed_states)
        if reply:
            await telegram.send_message(reply)
            if state.pending_digest:
                on_demand_requested = True

    # Step 4: Poll feeds (conditional GET, health tracking)
    fetcher = FeedFetcher()
    raw_items = await fetcher.fetch_all(config.sources, state)
    logger.info("feed polling completed", extra={"raw_items_count": len(raw_items)})

    # Check and alert for any newly auto-disabled feeds
    for src_id, f_state in state.feed_states.items():
        if f_state.get("auto_disabled") and not f_state.get("alert_sent"):
            f_state["alert_sent"] = True
            await telegram.send_message(
                f"⚠️ <b>Feed Health Alert</b>: Feed '<b>{html.escape(src_id)}</b>' failed "
                "5 consecutive times and was automatically disabled to protect run health. "
                "Use /status to inspect feed health."
            )

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

    # Check LLM budget alert (alert once at >= 80% daily capacity)
    llm = state.llm_usage
    calls_today = llm.get("calls_today", 0)
    tokens_today = llm.get("tokens_today", 0)
    if (calls_today >= 1200 or tokens_today >= 400_000) and not llm.get("quota_alert_sent"):
        llm["quota_alert_sent"] = True
        await telegram.send_message(
            f"⚠️ <b>LLM Budget Alert</b>: Daily summarization usage reached 80% "
            f"({calls_today} calls, {tokens_today:,} tokens). "
            "Bot will degrade to RSS snippet summaries if limit is reached."
        )

    # Queue new digest-eligible items from this run
    for sc in digest:
        itm_dict = item_to_digest_dict(
            sc.cluster.primary_item,
            cluster_size=sc.cluster.size,
            score=sc.score.total,
        )
        if not any(q.get("url") == itm_dict["url"] for q in state.digest_queue):
            state.digest_queue.append(itm_dict)

    # Check for scheduled digest slots
    local_dt = get_current_local_time(config.timezone)
    due_slot_key = check_due_digest_slots(
        local_dt=local_dt,
        digest_times=config.digest_times,
        digest_history=state.digest_history,
    )
    should_send_digest = bool(due_slot_key or on_demand_requested or state.pending_digest)
    digest_sent = False

    if should_send_digest:
        if state.paused and not (on_demand_requested or state.pending_digest):
            logger.info("bot is paused; skipping scheduled digest")
            if due_slot_key:
                state.digest_history[due_slot_key] = True
        else:
            # Filter out muted sectors
            active_items = [
                q for q in state.digest_queue if q.get("sector") not in state.muted_sectors
            ]
            active_items.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            top_digest_items = active_items[:8]

            if top_digest_items:
                for d_itm in top_digest_items:
                    if not d_itm.get("summary"):
                        txt, _ = await extractor.extract_text(
                            d_itm["url"],
                            extract_mode="full",
                            snippet_fallback="",
                        )
                        s_bullets, _ = await llm_orchestrator.summarize_story(
                            title=d_itm["headline"],
                            text=txt,
                            snippet="",
                            state=state,
                        )
                        d_itm["summary"] = s_bullets

                slot_label = (
                    "On-Demand Digest"
                    if (on_demand_requested or state.pending_digest)
                    else "Daily Digest"
                )
                digest_msgs = format_digest_messages(top_digest_items, slot_label=slot_label)
                for d_msg in digest_msgs:
                    await telegram.send_message(d_msg)

                digest_sent = True
                sent_urls = {itm["url"] for itm in top_digest_items}
                state.digest_queue = [
                    q for q in state.digest_queue if q.get("url") not in sent_urls
                ]
            elif on_demand_requested or state.pending_digest:
                await telegram.send_message("📰 No digest items available in queue at this time.")

            if due_slot_key:
                state.digest_history[due_slot_key] = True
            state.pending_digest = False

    # Prune state retention and persist
    state.prune_retention()
    state_manager.save_state(state)

    logger.info(
        "pipeline complete",
        extra={
            "dry_run": dry_run,
            "raw_items": len(raw_items),
            "breaking_count": len(breaking),
            "sent_messages": sent_count,
            "digest_sent": digest_sent,
        },
    )
