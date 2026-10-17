"""64-bit SimHash implementation for near-duplicate text detection."""

from __future__ import annotations

import hashlib
import re

_WORD_RE = re.compile(r"[\w']+")


def _tokenize(text: str) -> list[str]:
    """Normalize text and produce word unigrams and bigrams."""
    words = _WORD_RE.findall(text.lower())
    if not words:
        return []

    tokens: list[str] = list(words)
    # Add bigrams for structural context
    for i in range(len(words) - 1):
        tokens.append(f"{words[i]}_{words[i + 1]}")
    return tokens


def _hash_token(token: str) -> int:
    """Hash a token into a 64-bit integer."""
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    # Take first 8 bytes as unsigned 64-bit integer
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def compute_simhash(text: str) -> int:
    """Compute 64-bit SimHash fingerprint for input text."""
    tokens = _tokenize(text)
    if not tokens:
        return 0

    v = [0] * 64
    for token in tokens:
        h = _hash_token(token)
        for i in range(64):
            bit = (h >> i) & 1
            if bit:
                v[i] += 1
            else:
                v[i] -= 1

    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i

    return fingerprint


def hamming_distance(hash1: int, hash2: int) -> int:
    """Calculate the Hamming distance (differing bits) between two 64-bit hashes."""
    return (hash1 ^ hash2).bit_count()


def is_near_duplicate(hash1: int, hash2: int, max_distance: int = 14) -> bool:
    """Determine whether two fingerprints represent near-duplicate text."""
    if hash1 == 0 or hash2 == 0:
        return False
    return hamming_distance(hash1, hash2) <= max_distance
