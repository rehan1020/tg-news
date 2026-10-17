"""Article full-text extractor with SSRF defense, size caps, and RSS fallback."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from src.bot.logger import get_logger

logger = get_logger(__name__)

MAX_ARTICLE_CHARS = 4000
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024  # 2MB cap
EXTRACTION_TIMEOUT_SECONDS = 10.0
USER_AGENT = "telegram-news-bot/0.1.0 (+https://github.com/upstream/news-bot)"

# Strip non-content HTML elements
_TAG_STRIP_RE = re.compile(
    r"<(script|style|nav|footer|header|aside|form|svg|noscript|iframe)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAGS_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def is_private_ip(hostname: str) -> bool:
    """SSRF defense: verify that hostname does not resolve to private or loopback ranges."""
    try:
        # Resolve hostname to IP addresses
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_reserved
                or ip_obj.is_multicast
            ):
                return True
        return False
    except Exception:
        # If DNS fails or is suspicious, block
        return True


def clean_html_to_text(html_content: str) -> str:
    """Extract readable text from HTML by removing boilerplate tags."""
    if not html_content:
        return ""

    # Remove script, style, nav, footer, etc.
    cleaned = _TAG_STRIP_RE.sub(" ", html_content)
    # Remove all remaining HTML tags
    text = _HTML_TAGS_RE.sub(" ", cleaned)
    # Unescape HTML entities
    text = html.unescape(text)
    # Normalize whitespace
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[:MAX_ARTICLE_CHARS]


class ArticleExtractor:
    """Fetches and extracts clean article text while honoring robots and SSRF constraints."""

    def __init__(
        self,
        user_agent: str = USER_AGENT,
        timeout: float = EXTRACTION_TIMEOUT_SECONDS,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._robots_cache: dict[str, RobotFileParser] = {}

    async def can_fetch(self, url: str, client: httpx.AsyncClient) -> bool:
        """Check robots.txt permission for target URL."""
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return False

        base_url = f"{scheme}://{parsed.netloc}"
        if base_url not in self._robots_cache:
            rp = RobotFileParser()
            robots_url = f"{base_url}/robots.txt"
            try:
                resp = await client.get(
                    robots_url,
                    headers={"User-Agent": self._user_agent},
                    timeout=5.0,
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    # If 404 or missing, allow
                    rp.allow_all = True
            except Exception:
                rp.allow_all = True
            self._robots_cache[base_url] = rp

        rp = self._robots_cache[base_url]
        return rp.can_fetch(self._user_agent, url)

    async def extract_text(
        self,
        url: str,
        extract_mode: str = "full",
        snippet_fallback: str = "",
    ) -> tuple[str, bool]:
        """Extract full text from article URL.

        Returns:
            (extracted_text, is_rss_only_fallback)
        """
        # If configured as rss_only or non-http, return snippet immediately
        if extract_mode == "rss_only" or not url.startswith(("http://", "https://")):
            return (clean_html_to_text(snippet_fallback), True)

        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        # SSRF Defense check
        if is_private_ip(hostname):
            logger.warning("SSRF check blocked private IP host")
            return (clean_html_to_text(snippet_fallback), True)

        headers = {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                # Check robots.txt
                allowed = await self.can_fetch(url, client)
                if not allowed:
                    logger.info("robots.txt disallowed fetch, using snippet")
                    return (clean_html_to_text(snippet_fallback), True)

                # Fetch article HTML
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    logger.info(
                        "article fetch non-200, degrading to snippet",
                        extra={"status": resp.status_code},
                    )
                    return (clean_html_to_text(snippet_fallback), True)

                # Check payload size cap
                content = resp.text
                if len(content.encode("utf-8")) > self._max_bytes:
                    content = content[: self._max_bytes]

                text = clean_html_to_text(content)
                # If article text is too short (paywall or JS-rendered), fallback to snippet
                if len(text) < 150 and snippet_fallback:
                    return (clean_html_to_text(snippet_fallback), True)

                return (text, False)

        except Exception as e:
            logger.info("article fetch exception, degrading to snippet", extra={"error": str(e)})
            return (clean_html_to_text(snippet_fallback), True)
