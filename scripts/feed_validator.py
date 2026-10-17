#!/usr/bin/env python3
"""Validate configured feed URLs: reachability, XML validity, conditional GET support."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import feedparser
import httpx
import yaml

USER_AGENT = "telegram-news-bot/0.1.0 (+https://github.com/upstream/news-bot)"


async def validate_source(source: dict, client: httpx.AsyncClient) -> dict:
    source_id = source.get("id")
    url = source.get("url")
    enabled = source.get("enabled", True)

    result = {
        "id": source_id,
        "url": url,
        "enabled": enabled,
        "status": "SKIPPED",
        "http_code": None,
        "latency_ms": None,
        "entries_count": 0,
        "etag_support": False,
        "last_modified_support": False,
        "error": None,
    }

    if not enabled:
        result["status"] = "DISABLED"
        return result

    if not url or url.startswith("api://"):
        result["status"] = "API_SOURCE"
        return result

    t0 = time.monotonic()
    try:
        resp = await client.get(url, timeout=12.0, follow_redirects=True)
        latency = int((time.monotonic() - t0) * 1000)
        result["http_code"] = resp.status_code
        result["latency_ms"] = latency
        result["etag_support"] = "etag" in resp.headers
        result["last_modified_support"] = "last-modified" in resp.headers

        if resp.status_code != 200:
            result["status"] = f"HTTP_{resp.status_code}"
            return result

        parsed = feedparser.parse(resp.text)
        if parsed.bozo and not parsed.entries:
            result["status"] = "MALFORMED_XML"
            result["error"] = str(parsed.bozo_exception)
            return result

        result["entries_count"] = len(parsed.entries)
        result["status"] = "OK" if len(parsed.entries) > 0 else "EMPTY_FEED"

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = type(e).__name__

    return result


async def main_async() -> int:
    root = Path(__file__).resolve().parent.parent
    sources_file = root / "config" / "sources.yml"

    with open(sources_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    sources = data.get("sources", [])
    print(f"Validating {len(sources)} sources from {sources_file}...\n")

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [validate_source(s, client) for s in sources]
        results = await asyncio.gather(*tasks)

    # Print results
    print(
        f"{'ID':<18} | {'STATUS':<14} | {'HTTP':<5} | {'ITEMS':<6} | {'LATENCY':<8} | {'ETAG/LM'}"
    )
    print("-" * 75)

    failures = 0
    for r in results:
        status = r["status"]
        http_code = str(r["http_code"] or "-")
        items = str(r["entries_count"])
        lat = f"{r['latency_ms']}ms" if r["latency_ms"] else "-"
        cond = f"{'Y' if r['etag_support'] else 'N'}/{'Y' if r['last_modified_support'] else 'N'}"

        print(f"{r['id']:<18} | {status:<14} | {http_code:<5} | {items:<6} | {lat:<8} | {cond}")
        if status in ("ERROR", "MALFORMED_XML") or (r["http_code"] and r["http_code"] >= 400):
            failures += 1

    print("\nSummary:")
    print(f"  Total: {len(results)}, Failed/Unreachable: {failures}")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    import sys

    sys.exit(main())
