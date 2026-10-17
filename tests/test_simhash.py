"""Tests for SimHash fingerprinting and near-duplicate detection."""

from __future__ import annotations

from src.pipeline.simhash import compute_simhash, hamming_distance, is_near_duplicate


def test_identical_text_has_zero_distance():
    t1 = "Federal Reserve cuts interest rates by 25 basis points"
    t2 = "Federal Reserve cuts interest rates by 25 basis points"
    h1 = compute_simhash(t1)
    h2 = compute_simhash(t2)
    assert h1 != 0
    assert h1 == h2
    assert hamming_distance(h1, h2) == 0
    assert is_near_duplicate(h1, h2)


def test_near_duplicate_titles_detected():
    # Minor word variation across wire services
    t1 = "Federal Reserve cuts interest rates by 25 basis points in surprise move"
    t2 = "Federal Reserve cuts interest rate by 25 basis points in surprise decision"
    h1 = compute_simhash(t1)
    h2 = compute_simhash(t2)
    dist = hamming_distance(h1, h2)
    assert dist <= 14
    assert is_near_duplicate(h1, h2, max_distance=14)


def test_completely_different_titles_have_high_distance():
    t1 = "Federal Reserve cuts benchmark interest rates"
    t2 = "Bitcoin surges past eighty thousand dollars following major ETF inflows"
    h1 = compute_simhash(t1)
    h2 = compute_simhash(t2)
    dist = hamming_distance(h1, h2)
    assert dist > 10
    assert not is_near_duplicate(h1, h2, max_distance=5)


def test_empty_string_simhash():
    assert compute_simhash("") == 0
    assert not is_near_duplicate(0, 0)
