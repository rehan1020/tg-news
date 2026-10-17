"""Tests for outbound host allowlist verification script."""

from __future__ import annotations

from pathlib import Path

from scripts.check_hosts import get_configured_feed_hosts, main


def test_get_configured_feed_hosts():
    root = Path(__file__).resolve().parent.parent
    hosts = get_configured_feed_hosts(root)
    assert len(hosts) > 0
    assert "feeds.bbci.co.uk" in hosts
    assert "www.thehindu.com" in hosts


def test_main_check_hosts_passes():
    assert main() == 0
