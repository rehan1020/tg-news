"""Tests for article text extractor and SSRF prevention."""

from __future__ import annotations

import pytest
import respx

from src.extract.extractor import ArticleExtractor, clean_html_to_text, is_private_ip


def test_ssrf_blocks_private_and_loopback_ips():
    assert is_private_ip("127.0.0.1") is True
    assert is_private_ip("localhost") is True
    assert is_private_ip("10.0.0.5") is True
    assert is_private_ip("192.168.1.100") is True
    assert is_private_ip("169.254.169.254") is True  # Cloud metadata IP


def test_clean_html_strips_boilerplate_tags():
    raw_html = """
    <html>
      <head>
        <style>body { color: red; }</style>
        <script>console.log("malicious");</script>
      </head>
      <body>
        <nav><a href="/">Home</a><a href="/news">News</a></nav>
        <header><h1>Site Header</h1></header>
        <article>
          <h2>Economy Expands in Third Quarter</h2>
          <p>Gross domestic product grew at an annualized rate of 2.8 percent.</p>
        </article>
        <footer><p>Copyright 2026</p></footer>
      </body>
    </html>
    """
    text = clean_html_to_text(raw_html)
    assert "console.log" not in text
    assert "Site Header" not in text
    assert "Copyright 2026" not in text
    assert "Economy Expands in Third Quarter" in text
    assert "Gross domestic product grew" in text


@pytest.mark.asyncio
async def test_rss_only_mode_skips_fetch():
    extractor = ArticleExtractor()
    snippet = "Tech stocks rallied ahead of central bank rate announcement."
    text, is_fallback = await extractor.extract_text(
        url="https://example.com/paywalled-article",
        extract_mode="rss_only",
        snippet_fallback=snippet,
    )
    assert text == snippet
    assert is_fallback is True


@pytest.mark.asyncio
@respx.mock
async def test_paywalled_or_failed_article_degrades_to_snippet():
    extractor = ArticleExtractor()
    target_url = "https://example.com/article-403"
    snippet = "Government releases new economic data for manufacturing sector."

    respx.get(url__startswith=target_url).respond(status_code=403)
    respx.get("https://example.com/robots.txt").respond(status_code=404)

    text, is_fallback = await extractor.extract_text(
        url=target_url,
        extract_mode="full",
        snippet_fallback=snippet,
    )

    assert text == snippet
    assert is_fallback is True
