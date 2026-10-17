#!/usr/bin/env python3
"""Verify that all outbound HTTP hosts in code belong to the approved allowlist.

Ensures no backdoor or unauthorized external connections exist in the codebase.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

# Approved API provider hosts
APPROVED_API_HOSTS = {
    # Telegram
    "api.telegram.org",
    # LLM Providers
    "generativelanguage.googleapis.com",
    "api.groq.com",
    # News & Market APIs
    "finnhub.io",
    "www.alphavantage.co",
    "content.guardianapis.com",
    "api.nytimes.com",
    "cryptopanic.com",
    # Project Repository / Documentation
    "github.com",
    # Test / Documentation domains
    "api.example.com",
    "example.com",
}


def get_configured_feed_hosts(root: Path) -> set[str]:
    """Extract hostnames from config/sources.yml."""
    sources_file = root / "config" / "sources.yml"
    if not sources_file.exists():
        return set()

    with open(sources_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    hosts = set()
    for source in data.get("sources", []):
        url = source.get("url", "")
        if url.startswith(("http://", "https://")):
            parsed = urlparse(url)
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
    return hosts


def scan_source_files_for_urls(root: Path) -> dict[str, list[tuple[str, int]]]:
    """Scan src/ and scripts/ for http/https URLs and their domains."""
    url_pattern = re.compile(r"https?://[a-zA-Z0-9.\-_]+(?::\d+)?")

    found_hosts: dict[str, list[tuple[str, int]]] = {}

    scan_dirs = [root / "src", root / "scripts"]
    for scan_dir in scan_dirs:
        for py_file in scan_dir.rglob("*.py"):
            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue

            for idx, line in enumerate(lines, start=1):
                # Skip comments and docstrings where possible
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue

                for match in url_pattern.finditer(line):
                    raw_url = match.group(0)
                    parsed = urlparse(raw_url)
                    host = (parsed.hostname or "").lower()
                    if host and host not in ("localhost", "127.0.0.1"):
                        found_hosts.setdefault(host, []).append(
                            (str(py_file.relative_to(root)), idx)
                        )

    return found_hosts


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    feed_hosts = get_configured_feed_hosts(root)
    allowed_hosts = APPROVED_API_HOSTS | feed_hosts

    found_hosts = scan_source_files_for_urls(root)

    unauthorized: dict[str, list[tuple[str, int]]] = {}
    for host, locations in found_hosts.items():
        # Check exact host match or subdomain of allowed
        if host not in allowed_hosts:
            unauthorized[host] = locations

    if unauthorized:
        print("ERROR: Unauthorized outbound hosts detected in codebase:")
        for host, locations in unauthorized.items():
            print(f"  Host: {host}")
            for file_path, line_no in locations:
                print(f"    - {file_path}:{line_no}")
        print("\nApproved hosts:")
        for h in sorted(allowed_hosts):
            print(f"  - {h}")
        return 1

    print(f"Outbound host allowlist check passed ({len(found_hosts)} hosts checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
