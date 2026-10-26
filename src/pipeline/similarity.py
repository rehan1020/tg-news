"""Headline similarity and story matching engine for cross-source deduplication."""

from __future__ import annotations

import hashlib
import itertools
import re
from difflib import SequenceMatcher

STOP_WORDS = {
    "a",
    "about",
    "after",
    "ahead",
    "all",
    "amid",
    "amidst",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "breaking",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "exclusive",
    "explained",
    "first",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "live",
    "more",
    "new",
    "news",
    "now",
    "of",
    "on",
    "opinion",
    "or",
    "out",
    "over",
    "report",
    "reported",
    "reports",
    "said",
    "says",
    "saying",
    "second",
    "should",
    "so",
    "than",
    "that",
    "the",
    "these",
    "this",
    "those",
    "to",
    "today",
    "updates",
    "video",
    "was",
    "watch",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
    "yesterday",
}

# Generic institutional words that are common across news and shouldn't alone trigger a match
GENERIC_INSTITUTIONS = {
    "administration",
    "agency",
    "authorities",
    "cabinet",
    "centre",
    "court",
    "department",
    "government",
    "high",
    "minister",
    "ministry",
    "official",
    "officials",
    "parliament",
    "police",
    "pm",
    "president",
    "spokesperson",
    "state",
    "supreme",
}

# Editorial prefixes commonly prepended to headlines
_EDITORIAL_PREFIX_RE = re.compile(
    r"^(breaking(\s+news)?|exclusive|update|updates|watch|live(\s+updates)?|explained|opinion|analysis|just\s+in)\s*[:|-]\s*",
    re.IGNORECASE,
)

# Common publisher branding suffixes
_PUBLISHER_SUFFIX_RE = re.compile(
    r"\s*[-|–—|]\s*(the\s+)?"
    r"(reuters|bbc|times\s+of\s+india|hindustan\s+times|news18|ndtv|al\s+jazeera|france\s+24|"
    r"cnn|bloomberg|ap|associated\s+press|cnbc|wsj|guardian|dw|politico|un\s+news|npr).*$",
    re.IGNORECASE,
)


def stem(word: str) -> str:
    """Lightweight rule-based stemmer to unify plurals and verb inflections."""
    word = re.sub(r"'s$", "", word)
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("es") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def normalize_headline(title: str) -> tuple[str, list[str]]:
    """Clean editorial prefixes/suffixes and extract stemmed content words.

    Returns:
        (cleaned_raw_title, list_of_stemmed_content_words)
    """
    if not title:
        return "", []

    t = _EDITORIAL_PREFIX_RE.sub("", title.strip())
    t = _PUBLISHER_SUFFIX_RE.sub("", t).strip()

    words = re.findall(r"[\w]+", t.lower())
    content = [stem(w) for w in words if w not in STOP_WORDS and len(w) > 1]
    return t, content


def are_headlines_similar(
    title1: str,
    title2: str,
    sector1: str = "",
    sector2: str = "",
) -> bool:
    """Determine whether two headlines from different sources cover the same event.

    Args:
        title1: First headline string.
        title2: Second headline string.
        sector1: Sector of first story (e.g. 'world', 'india').
        sector2: Sector of second story.

    Returns:
        True if the headlines represent multi-source coverage of the same news event.
    """
    if not title1 or not title2:
        return False

    # Check sector compatibility if provided
    if sector1 and sector2:
        s1, s2 = sector1.lower(), sector2.lower()
        if s1 != s2 and not ({s1, s2} <= {"business", "markets"}):
            return False

    raw_norm1, c1 = normalize_headline(title1)
    raw_norm2, c2 = normalize_headline(title2)

    # 1. Direct character similarity on cleaned raw titles (SequenceMatcher)
    seq_ratio = SequenceMatcher(None, raw_norm1.lower(), raw_norm2.lower()).ratio()
    if seq_ratio >= 0.70:
        return True

    s1, s2 = set(c1), set(c2)
    if not s1 or not s2:
        return False

    shared = s1 & s2
    if not shared:
        return False

    min_len = min(len(s1), len(s2))
    overlap = len(shared) / min_len if min_len > 0 else 0
    jaccard = len(shared) / len(s1 | s2) if len(s1 | s2) > 0 else 0

    non_generic = shared - GENERIC_INSTITUTIONS

    # 2. Strong content word overlap: at least 2 specific entities and high overlap
    if len(non_generic) >= 2 and (overlap >= 0.50 or jaccard >= 0.35):
        return True

    # 3. 3 or more specific shared entities with reasonable overlap
    return bool(len(non_generic) >= 3 and overlap >= 0.40)


def compute_story_hashes(title: str) -> list[str]:
    """Compute deterministic cryptographic entity pair hashes for cross-run tracking.

    Contains only SHA-256 hex strings, preserving zero-plaintext security invariants.
    """
    _, content = normalize_headline(title)
    non_generic = sorted(set(content) - GENERIC_INSTITUTIONS)
    if len(non_generic) < 2:
        non_generic = sorted(set(content))
    if len(non_generic) < 2:
        return []

    # Generate SHA-256 hashes of 2-word combinations for up to 8 core terms
    hashes: list[str] = []
    for w1, w2 in itertools.combinations(non_generic[:8], 2):
        h = hashlib.sha256(f"{w1}_{w2}".encode()).hexdigest()
        hashes.append(h)
    return hashes


def is_story_seen(
    title: str,
    seen_story_hashes: dict[str, float],
    min_matches: int = 2,
) -> bool:
    """Check if a story was already sent/covered in a previous run."""
    if not seen_story_hashes or not title:
        return False
    hashes = compute_story_hashes(title)
    if not hashes:
        return False
    matches = sum(1 for h in hashes if h in seen_story_hashes)
    return matches >= min_matches
