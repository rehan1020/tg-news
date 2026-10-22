"""Pipeline orchestrator — runs each step in sequence."""

from __future__ import annotations

import asyncio
import html
import os
import random
from typing import Any

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
    format_sector_digest_messages,
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


async def run(
    *,
    dry_run: bool = False,
    force_digest: bool = False,
    force_crypto: bool = False,
    force_markets: bool = False,
    force_world: bool = False,
    force_india: bool = False,
    config_override: BotConfig | None = None,
) -> None:
    """Execute the full bot pipeline."""
    config = config_override or load_config(dry_run=dry_run)
    force_crypto = force_crypto or os.environ.get("FORCE_CRYPTO", "").lower() in (
        "true",
        "1",
        "yes",
    )
    force_markets = force_markets or os.environ.get("FORCE_MARKETS", "").lower() in (
        "true",
        "1",
        "yes",
    )
    force_world = force_world or os.environ.get("FORCE_WORLD", "").lower() in (
        "true",
        "1",
        "yes",
    )
    force_india = force_india or os.environ.get("FORCE_INDIA", "").lower() in (
        "true",
        "1",
        "yes",
    )

    # Step 1: Random start delay (apply on scheduled cron, skip on manual/external dispatch)
    is_manual = os.environ.get("GITHUB_EVENT_NAME") in ("workflow_dispatch", "repository_dispatch")
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
    on_crypto_requested = False
    on_markets_requested = False
    on_world_requested = False
    on_india_requested = False

    # Check for command passed directly via external repository dispatch (e.g. Cloudflare webhook)
    dispatch_cmd = os.environ.get("DISPATCH_COMMAND", "").strip()
    if dispatch_cmd:
        logger.info("processing dispatch command from payload", extra={"command": dispatch_cmd})
        reply = handle_command(dispatch_cmd, state, feed_health=state.feed_states)
        if reply:
            await telegram.send_message(reply)
            if state.pending_digest:
                on_demand_requested = True
            if state.pending_crypto:
                on_crypto_requested = True
            if state.pending_markets:
                on_markets_requested = True
            if state.pending_world:
                on_world_requested = True
            if state.pending_india:
                on_india_requested = True

    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        text = msg.get("text", "")
        reply = handle_command(text, state, feed_health=state.feed_states)
        if reply:
            await telegram.send_message(reply)
            if state.pending_digest:
                on_demand_requested = True
            if state.pending_crypto:
                on_crypto_requested = True
            if state.pending_markets:
                on_markets_requested = True
            if state.pending_world:
                on_world_requested = True
            if state.pending_india:
                on_india_requested = True

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
    should_send_digest = bool(
        due_slot_key or on_demand_requested or state.pending_digest or force_digest
    )
    digest_sent = False

    if should_send_digest:
        if state.paused and not (on_demand_requested or state.pending_digest or force_digest):
            logger.info("bot is paused; skipping scheduled digest")
            if due_slot_key:
                state.digest_history[due_slot_key] = True
        else:
            # Filter out muted sectors and balance across sectors
            active_items = [
                q for q in state.digest_queue if q.get("sector") not in state.muted_sectors
            ]
            top_digest_items = _select_balanced_digest_items(active_items, max_items=8)

            # In force_digest mode, if queue had few items, backfill from freshest clusters
            if len(top_digest_items) < 4 and force_digest and clusters:
                seen_urls = {q.get("url") for q in top_digest_items}
                for cl in clusters:
                    if len(top_digest_items) >= 8:
                        break
                    p_itm = cl.primary_item
                    if p_itm.url not in seen_urls and p_itm.sector not in state.muted_sectors:
                        seen_urls.add(p_itm.url)
                        top_digest_items.append(
                            item_to_digest_dict(p_itm, cluster_size=cl.size, score=0.6)
                        )

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

                if on_demand_requested or state.pending_digest:
                    slot_label = "On-Demand Digest"
                elif force_digest:
                    slot_label = "Daily Digest (Test Run)"
                else:
                    slot_label = "Daily Digest"
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

    # Step 10: On-demand Crypto Intelligence dispatch
    if (on_crypto_requested or state.pending_crypto or force_crypto) and not state.paused:
        logger.info(
            "processing on-demand crypto request",
            extra={"filter": state.pending_crypto_filter},
        )
        crypto_items = _collect_sector_items(
            sector="crypto",
            clusters=clusters,
            raw_items=raw_items,
            digest_queue=state.digest_queue,
            filter_term=state.pending_crypto_filter,
            max_items=8,
        )
        if crypto_items:
            for c_itm in crypto_items:
                if not c_itm.get("summary"):
                    txt, _ = await extractor.extract_text(
                        c_itm["url"],
                        extract_mode="full",
                        snippet_fallback="",
                    )
                    s_bullets, _ = await llm_orchestrator.summarize_story(
                        title=c_itm["headline"],
                        text=txt,
                        snippet="",
                        state=state,
                    )
                    c_itm["summary"] = s_bullets
            c_msgs = format_sector_digest_messages(
                crypto_items,
                title="Crypto Market & Trading Intelligence",
                icon="🪙",
                filter_term=state.pending_crypto_filter,
            )
            for m in c_msgs:
                await telegram.send_message(m)
        else:
            await telegram.send_message(
                "🪙 No active crypto market stories found matching your request right now."
            )
        state.pending_crypto = False
        state.pending_crypto_filter = ""

    # Step 11: On-demand Markets & Business/Macro dispatch
    if (on_markets_requested or state.pending_markets or force_markets) and not state.paused:
        logger.info(
            "processing on-demand markets/business request",
            extra={"filter": state.pending_markets_filter},
        )
        market_items = _collect_sector_items(
            sector=("markets", "business"),
            clusters=clusters,
            raw_items=raw_items,
            digest_queue=state.digest_queue,
            filter_term=state.pending_markets_filter,
            max_items=8,
        )
        if market_items:
            for m_itm in market_items:
                if not m_itm.get("summary"):
                    txt, _ = await extractor.extract_text(
                        m_itm["url"],
                        extract_mode="full",
                        snippet_fallback="",
                    )
                    s_bullets, _ = await llm_orchestrator.summarize_story(
                        title=m_itm["headline"],
                        text=txt,
                        snippet="",
                        state=state,
                    )
                    m_itm["summary"] = s_bullets
            m_msgs = format_sector_digest_messages(
                market_items,
                title="Business, Macro & Market Intelligence",
                icon="📈",
                filter_term=state.pending_markets_filter,
            )
            for m in m_msgs:
                await telegram.send_message(m)
        else:
            await telegram.send_message(
                "📈 No active business or market stories found matching your request right now."
            )
        state.pending_markets = False
        state.pending_markets_filter = ""

    # Step 12: On-demand World & Geopolitics dispatch
    if (on_world_requested or state.pending_world or force_world) and not state.paused:
        logger.info(
            "processing on-demand world request",
            extra={"filter": state.pending_world_filter},
        )
        world_items = _collect_sector_items(
            sector="world",
            clusters=clusters,
            raw_items=raw_items,
            digest_queue=state.digest_queue,
            filter_term=state.pending_world_filter,
            max_items=8,
        )
        if world_items:
            for w_itm in world_items:
                if not w_itm.get("summary"):
                    txt, _ = await extractor.extract_text(
                        w_itm["url"],
                        extract_mode="full",
                        snippet_fallback="",
                    )
                    s_bullets, _ = await llm_orchestrator.summarize_story(
                        title=w_itm["headline"],
                        text=txt,
                        snippet="",
                        state=state,
                    )
                    w_itm["summary"] = s_bullets
            w_msgs = format_sector_digest_messages(
                world_items,
                title="World & Geopolitical Intelligence",
                icon="🌍",
                filter_term=state.pending_world_filter,
            )
            for m in w_msgs:
                await telegram.send_message(m)
        else:
            await telegram.send_message(
                "🌍 No active world or geopolitical stories found matching your request right now."
            )
        state.pending_world = False
        state.pending_world_filter = ""

    # Step 13: On-demand India & National dispatch
    if (on_india_requested or state.pending_india or force_india) and not state.paused:
        logger.info(
            "processing on-demand india request",
            extra={"filter": state.pending_india_filter},
        )
        india_items = _collect_sector_items(
            sector="india",
            clusters=clusters,
            raw_items=raw_items,
            digest_queue=state.digest_queue,
            filter_term=state.pending_india_filter,
            max_items=8,
        )
        if india_items:
            for i_itm in india_items:
                if not i_itm.get("summary"):
                    txt, _ = await extractor.extract_text(
                        i_itm["url"],
                        extract_mode="full",
                        snippet_fallback="",
                    )
                    s_bullets, _ = await llm_orchestrator.summarize_story(
                        title=i_itm["headline"],
                        text=txt,
                        snippet="",
                        state=state,
                    )
                    i_itm["summary"] = s_bullets
            i_msgs = format_sector_digest_messages(
                india_items,
                title="India & National News Intelligence",
                icon="🇮🇳",
                filter_term=state.pending_india_filter,
            )
            for m in i_msgs:
                await telegram.send_message(m)
        else:
            await telegram.send_message(
                "🇮🇳 No active India or national news stories found matching your request right now."
            )
        state.pending_india = False
        state.pending_india_filter = ""

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


def _collect_sector_items(
    sector: str | tuple[str, ...] | list[str] | set[str],
    clusters: list[Any],
    raw_items: list[Any],
    digest_queue: list[dict[str, Any]],
    filter_term: str = "",
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Gather and rank items for a specific sector or sectors, optionally filtering by keyword."""
    items_by_url: dict[str, dict[str, Any]] = {}
    term_lower = filter_term.lower().strip()
    sectors = {s.lower() for s in (sector if isinstance(sector, list | tuple | set) else [sector])}

    # 1. From clusters
    for cl in clusters:
        p = cl.primary_item
        if p.sector.lower() in sectors:
            if (
                term_lower
                and term_lower not in p.title.lower()
                and term_lower not in (p.summary_raw or "").lower()
            ):
                continue
            itm = item_to_digest_dict(p, cluster_size=cl.size, score=0.7)
            items_by_url[itm["url"]] = itm

    # 2. Check raw items for any other stories
    for r in raw_items:
        if r.sector.lower() in sectors and r.url not in items_by_url:
            if (
                term_lower
                and term_lower not in r.title.lower()
                and term_lower not in (r.summary_raw or "").lower()
            ):
                continue
            itm = item_to_digest_dict(r, cluster_size=1, score=0.6)
            items_by_url[itm["url"]] = itm

    # 3. Check digest queue
    for q in digest_queue:
        if q.get("sector", "").lower() in sectors and q.get("url") not in items_by_url:
            if term_lower and term_lower not in q.get("headline", "").lower():
                continue
            items_by_url[q["url"]] = dict(q)

    collected = list(items_by_url.values())
    collected.sort(
        key=lambda x: (x.get("score", 0.0), x.get("published_at", 0.0)),
        reverse=True,
    )
    return collected[:max_items]


def _select_balanced_digest_items(
    items: list[dict[str, Any]],
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Select items balancing across sectors via round-robin, prioritized by score."""
    if not items:
        return []
    if len(items) <= max_items:
        return sorted(items, key=lambda x: x.get("score", 0.0), reverse=True)

    # Group by sector, sorted descending by score within each sector
    by_sector: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(items, key=lambda x: x.get("score", 0.0), reverse=True):
        sec = item.get("sector", "other")
        by_sector.setdefault(sec, []).append(item)

    # Preferred sector ordering for round-robin
    preferred_order = ["world", "india", "business", "markets", "crypto"]
    # Include any sectors not in preferred_order at the end
    ordered_sectors = [s for s in preferred_order if s in by_sector] + [
        s for s in by_sector if s not in preferred_order
    ]

    selected: list[dict[str, Any]] = []
    indices: dict[str, int] = {s: 0 for s in ordered_sectors}

    while len(selected) < max_items:
        added_in_round = False
        for sec in ordered_sectors:
            idx = indices[sec]
            sec_items = by_sector[sec]
            if idx < len(sec_items):
                selected.append(sec_items[idx])
                indices[sec] += 1
                added_in_round = True
                if len(selected) >= max_items:
                    break
        if not added_in_round:
            break

    return selected
