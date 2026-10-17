"""Data models for feeds and news items."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FeedItem:
    """A single normalized news item extracted from a feed."""

    id: str  # Unique canonical hash
    title: str
    url: str
    canonical_url: str
    source_id: str
    source_name: str
    sector: str
    trust_tier: str  # official | major | specialist | aggregator
    published_at: float  # epoch timestamp
    summary_raw: str = ""
    authors: tuple[str, ...] = ()
    simhash: int = 0
    raw_entry: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class FeedHealth:
    """Health metadata for a feed source."""

    source_id: str
    consecutive_failures: int = 0
    etag: str | None = None
    last_modified: str | None = None
    last_status: int = 0
    last_fetch_time: float = 0.0
    enabled: bool = True
