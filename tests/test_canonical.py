"""Tests for URL canonicalization and hashing."""

from __future__ import annotations

from src.pipeline.canonical import canonicalize_url, hash_url


def test_strip_tracking_parameters():
    url = "https://example.com/news/article-1?utm_source=twitter&utm_medium=social&utm_campaign=breaking&real_param=123"
    canonical = canonicalize_url(url)
    assert "utm_source" not in canonical
    assert "utm_medium" not in canonical
    assert "utm_campaign" not in canonical
    assert "real_param=123" in canonical


def test_strip_facebook_and_google_click_ids():
    url = "https://news.example.com/story?fbclid=xyz123&gclid=abc456&id=42"
    canonical = canonicalize_url(url)
    assert "fbclid" not in canonical
    assert "gclid" not in canonical
    assert "id=42" in canonical


def test_strip_fragment():
    url = "https://example.com/article#comments-section"
    canonical = canonicalize_url(url)
    assert "#" not in canonical
    assert canonical == "https://example.com/article"


def test_lowercase_scheme_and_host():
    url = "HTTPS://WWW.EXAMPLE.COM/Path/To/Page"
    canonical = canonicalize_url(url)
    assert canonical.startswith("https://www.example.com/Path/To/Page")


def test_strip_trailing_slash_on_path():
    url = "https://example.com/news/economy/"
    canonical = canonicalize_url(url)
    assert canonical == "https://example.com/news/economy"


def test_deterministic_hash_url():
    url1 = "https://example.com/post?utm_source=rss&id=99"
    url2 = "https://example.com/post?id=99&utm_medium=feed"
    # Both URLs canonicalize to same string, hence same SHA256 hash
    assert hash_url(url1) == hash_url(url2)
    assert len(hash_url(url1)) == 64
