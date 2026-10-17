"""URL canonicalization and hashing for deduplication.

Strips tracking params, normalizes schemes/domains, and generates deterministic SHA256 hashes.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Common tracking parameters to strip
TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "mc_eid",
        "mc_cid",
        "ref",
        "ref_src",
        "source",
        "soc_src",
        "soc_trk",
        "feature",
    }
)


def canonicalize_url(url: str) -> str:
    """Normalize a URL to its canonical form for deduplication.

    1. Lowercase scheme and hostname
    2. Remove URL fragment
    3. Strip tracking query parameters
    4. Sort remaining query parameters
    5. Strip trailing slashes on root or path (unless path is empty)
    """
    if not url:
        return ""

    parsed = urlparse(url.strip())

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Drop default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Normalize path
    path = parsed.path
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")

    # Filter query parameters
    if parsed.query:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
        cleaned_pairs = [(k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS]
        cleaned_pairs.sort()
        query = urlencode(cleaned_pairs)
    else:
        query = ""

    # Fragment is dropped entirely
    canonical = urlunparse((scheme, netloc, path, parsed.params, query, ""))
    return canonical


def hash_url(url: str) -> str:
    """Return deterministic SHA256 hex digest of the canonicalized URL."""
    canonical = canonicalize_url(url)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
