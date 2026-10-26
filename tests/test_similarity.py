"""Tests for headline similarity, story hashing, and cross-source deduplication."""

from __future__ import annotations

import time

from src.feeds.models import FeedItem
from src.pipeline.clustering import cluster_items
from src.pipeline.similarity import (
    are_headlines_similar,
    compute_story_hashes,
    is_story_seen,
    normalize_headline,
)


def _make_item(
    title: str,
    source_id: str = "test",
    sector: str = "world",
    trust_tier: str = "major",
) -> FeedItem:
    return FeedItem(
        id=f"hash_{abs(hash(title))}",
        title=title,
        url=f"https://example.com/{abs(hash(title))}",
        canonical_url=f"https://example.com/{abs(hash(title))}",
        source_id=source_id,
        source_name=source_id.upper(),
        sector=sector,
        trust_tier=trust_tier,
        published_at=time.time(),
    )


def test_normalize_headline():
    raw = "Breaking: Cyclone Dana updates: 5 lakh evacuated in Odisha - The Times of India"
    t, content = normalize_headline(raw)
    assert not t.startswith("Breaking:")
    assert not t.endswith("Times of India")
    assert "cyclone" in content
    assert "dana" in content
    assert "odisha" in content


def test_are_headlines_similar_positives():
    # Multi-source coverage of the same event with different wording
    assert are_headlines_similar(
        "Israel launches strikes against Iran, military says",
        "Israel attacks military targets in Iran in retaliation for missile barrage",
        sector1="world",
        sector2="world",
    )
    assert are_headlines_similar(
        "Israel launches strikes against Iran, military says",
        "Explosions heard in Tehran as Israel confirms strikes on Iran",
        sector1="world",
        sector2="world",
    )
    assert are_headlines_similar(
        "Cyclone Dana: Over 5 lakh evacuated in Odisha, flight operations suspended in Kolkata",
        "Cyclone Dana landfall updates: Odisha evacuates 500,000 people; Kolkata airport shuts",
        sector1="india",
        sector2="india",
    )
    assert are_headlines_similar(
        "US Fed cuts benchmark interest rate by 25 basis points",
        "Federal Reserve cuts rates by 25 basis points as inflation cools",
        sector1="markets",
        sector2="business",
    )
    assert are_headlines_similar(
        "India, China reach agreement on patrolling along LAC in eastern Ladakh",
        "India and China reach pact on border patrolling along Line of Actual Control",
        sector1="india",
        sector2="india",
    )


def test_are_headlines_similar_negatives():
    # Different events that share only generic or single entities must NOT match
    assert not are_headlines_similar(
        "Israel launches strikes against Iran, military says",
        "Israel says 5 soldiers killed in southern Lebanon fighting",
        sector1="world",
        sector2="world",
    )
    assert not are_headlines_similar(
        "Supreme Court stays Allahabad High Court order on UP Madarsa Act",
        "Supreme Court grants bail to Manish Sisodia in Delhi excise policy case",
        sector1="india",
        sector2="india",
    )
    assert not are_headlines_similar(
        "RBI keeps repo rate unchanged at 6.5%",
        "RBI imposes monetary penalty on three cooperative banks",
        sector1="business",
        sector2="business",
    )
    assert not are_headlines_similar(
        "Odisha prepares for Cyclone Dana",
        "Odisha government announces hike in dearness allowance for state employees",
        sector1="india",
        sector2="india",
    )
    # Different sectors must not match
    assert not are_headlines_similar(
        "Major election results announced",
        "Major election results announced",
        sector1="world",
        sector2="india",
    )


def test_cluster_items_merges_multi_source_coverage():
    """Different newsrooms reporting the same event are merged into 1 cluster."""
    i1 = _make_item(
        "Cyclone Dana: Over 5 lakh evacuated in Odisha, flights suspended in Kolkata",
        source_id="thehindu",
        sector="india",
        trust_tier="major",
    )
    i2 = _make_item(
        "Cyclone Dana landfall: Odisha evacuates thousands ahead of storm; Kolkata airport shuts",
        source_id="timesofindia",
        sector="india",
        trust_tier="major",
    )
    i3 = _make_item(
        "Odisha evacuates 5 lakh people as Cyclone Dana approaches coast",
        source_id="news18",
        sector="india",
        trust_tier="major",
    )
    # An unrelated story in the same sector
    i4 = _make_item(
        "Supreme Court grants bail to Manish Sisodia in Delhi excise policy case",
        source_id="ndtv",
        sector="india",
        trust_tier="major",
    )

    clusters = cluster_items([i1, i2, i3, i4])
    # Exactly 2 clusters: 1 for Cyclone Dana (size 3) and 1 for Sisodia (size 1)
    assert len(clusters) == 2
    dana_cluster = next(c for c in clusters if "dana" in c.primary_item.title.lower())
    assert dana_cluster.size == 3
    assert dana_cluster.sources == {"thehindu", "timesofindia", "news18"}


def test_story_hashes_and_is_story_seen():
    t_prev = "Cyclone Dana: Over 5 lakh evacuated in Odisha, flight operations suspended in Kolkata"
    hashes = compute_story_hashes(t_prev)
    assert len(hashes) >= 1
    seen_dict = {h: time.time() for h in hashes}

    t_same = "Cyclone Dana landfall updates: Odisha evacuates 500,000 people; Kolkata airport shuts"
    t_diff = "Supreme Court grants bail to Manish Sisodia in Delhi excise policy case"

    assert is_story_seen(t_same, seen_dict) is True
    assert is_story_seen(t_diff, seen_dict) is False
