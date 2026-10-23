"""Feed fetcher with conditional GET, bounded concurrency, and health tracking."""

from __future__ import annotations

import asyncio
import calendar
import time
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from src.bot.logger import get_logger
from src.extract.extractor import clean_html_to_text
from src.feeds.models import FeedItem
from src.pipeline.canonical import canonicalize_url, hash_url
from src.pipeline.simhash import compute_simhash
from src.state.manager import BotState

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_CONCURRENT_FEEDS = 5
PER_DOMAIN_DELAY_SECONDS = 0.5
USER_AGENT = "telegram-news-bot/0.1.0 (+https://github.com/upstream/news-bot)"


MAX_CONSECUTIVE_FAILURES = 5


class FeedFetcher:
    """Async feed fetcher implementing conditional GET and domain throttling."""

    def __init__(
        self,
        user_agent: str = USER_AGENT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_concurrency: int = MAX_CONCURRENT_FEEDS,
        domain_delay: float = PER_DOMAIN_DELAY_SECONDS,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._domain_delay = domain_delay
        self._domain_last_request: dict[str, float] = {}
        self._domain_lock = asyncio.Lock()

    async def _throttle_domain(self, domain: str) -> None:
        """Enforce delay between requests to the same domain."""
        async with self._domain_lock:
            now = time.monotonic()
            last = self._domain_last_request.get(domain, 0.0)
            wait = self._domain_delay - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._domain_last_request[domain] = time.monotonic()

    async def fetch_feed(
        self,
        source: dict[str, Any],
        state: BotState,
        client: httpx.AsyncClient,
    ) -> list[FeedItem]:
        """Fetch and parse a single feed source, honoring conditional GET headers."""
        source_id = source.get("id", "unknown")
        url = source.get("url", "")
        sector = source.get("sector", "world")
        trust_tier = source.get("trust_tier", "major")
        source_name = source.get("name", source_id)

        # Skip disabled feeds or non-http API endpoints in basic RSS fetcher
        if not source.get("enabled", True):
            return []

        # Check if feed has been auto-disabled in state due to prior consecutive failures
        feed_state = state.feed_states.setdefault(source_id, {})
        if feed_state.get("auto_disabled") or not feed_state.get("enabled", True):
            logger.info("skipping auto-disabled feed", extra={"source_id": source_id})
            return []

        if url.startswith("api://"):
            logger.info(
                "skipping api source in standard rss fetcher", extra={"source_id": source_id}
            )
            return []

        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()

        # Retrieve prior feed health/conditional headers from state
        etag = feed_state.get("etag")
        last_modified = feed_state.get("last_modified")

        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        def _record_failure(err_str: str, status_code: int = 0) -> None:
            consecutive = feed_state.get("consecutive_failures", 0) + 1
            feed_state["consecutive_failures"] = consecutive
            feed_state["last_fetch_time"] = time.time()
            if status_code:
                feed_state["last_status"] = status_code
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                feed_state["enabled"] = False
                feed_state["auto_disabled"] = True
                logger.warning(
                    "feed auto-disabled due to consecutive failures",
                    extra={"source_id": source_id, "failures": consecutive},
                )
            else:
                logger.warning(
                    "feed fetch failed",
                    extra={"source_id": source_id, "error": err_str, "failures": consecutive},
                )

        async with self._semaphore:
            await self._throttle_domain(domain)
            try:
                response = await client.get(
                    url,
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=True,
                )
            except Exception as e:
                _record_failure(str(e))
                return []

        # Handle 304 Not Modified
        if response.status_code == 304:
            feed_state["consecutive_failures"] = 0
            feed_state["last_fetch_time"] = time.time()
            feed_state["last_status"] = 304
            logger.info("feed not modified (304)", extra={"source_id": source_id})
            return []

        # Handle HTTP errors
        if response.status_code != 200:
            _record_failure(f"HTTP {response.status_code}", response.status_code)
            return []

        # Success: update conditional cache headers and reset failures
        feed_state["consecutive_failures"] = 0
        feed_state["auto_disabled"] = False
        feed_state["enabled"] = True
        feed_state["alert_sent"] = False
        feed_state["last_status"] = 200
        feed_state["last_fetch_time"] = time.time()
        new_etag = response.headers.get("etag")
        new_last_mod = response.headers.get("last-modified")
        if new_etag:
            feed_state["etag"] = new_etag
        if new_last_mod:
            feed_state["last_modified"] = new_last_mod

        # Parse RSS / Atom XML
        content = response.text
        parsed = feedparser.parse(content)

        items: list[FeedItem] = []
        now = time.time()

        for entry in parsed.entries:
            title = clean_html_to_text(entry.get("title", "")).strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            # Compute canonical URL and ID
            canonical = canonicalize_url(link)
            item_id = hash_url(canonical)

            # Determine published timestamp
            published_at = now
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published_at = float(calendar.timegm(entry.published_parsed))
                except Exception:
                    published_at = now
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                try:
                    published_at = float(calendar.timegm(entry.updated_parsed))
                except Exception:
                    published_at = now

            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary = clean_html_to_text(summary_raw).strip()
            simhash_val = compute_simhash(title)

            authors_list: list[str] = []
            if "author" in entry:
                authors_list.append(str(entry.author))

            item = FeedItem(
                id=item_id,
                title=title,
                url=link,
                canonical_url=canonical,
                source_id=source_id,
                source_name=source_name,
                sector=sector,
                trust_tier=trust_tier,
                published_at=published_at,
                summary_raw=summary,
                authors=tuple(authors_list),
                simhash=simhash_val,
            )
            items.append(item)

        logger.info(
            "feed parsed successfully",
            extra={"source_id": source_id, "items_count": len(items)},
        )
        return items

    async def fetch_all(
        self,
        sources: tuple[dict[str, Any], ...],
        state: BotState,
    ) -> list[FeedItem]:
        """Fetch all configured feeds concurrently within semaphore limits."""
        limits = httpx.Limits(max_connections=MAX_CONCURRENT_FEEDS * 2, max_keepalive_connections=5)
        async with httpx.AsyncClient(limits=limits, timeout=self._timeout) as client:
            tasks = [self.fetch_feed(source, state, client) for source in sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[FeedItem] = []
        for res in results:
            if isinstance(res, list):
                all_items.extend(res)
            elif isinstance(res, Exception):
                logger.warning("unexpected error during feed fetch task", extra={"error": str(res)})

        return all_items
