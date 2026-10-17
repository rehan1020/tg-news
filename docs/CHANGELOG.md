# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-17

### Added
- **Phase 0 (Scaffold)**:
  - Repository structure, pyproject.toml, requirements.txt with pinned dependencies.
  - Hardened GitHub Actions workflows (`run.yml`, `keepalive.yml`, `ci.yml`) with minimal permissions and SHA-pinned actions.
  - Central `RedactingFilter` in `src/bot/logger.py` redacting known secrets, token patterns, and query params from log records.
  - Environment loader in `src/bot/config.py` supporting `.env`, environment overrides, and local YAML merges.
  - Helper scripts: `generate_state_key.py`, `local_dry_run.py`, `check_hosts.py`.
- **Phase 1 (Ingest, Dedupe, State, Headlines)**:
  - Feed fetcher with conditional GET (`ETag`, `Last-Modified`), per-domain throttling, and health tracking in `src/feeds/fetcher.py`.
  - Live feed validator script `scripts/feed_validator.py` verifying all 24 candidates across 5 sectors.
  - URL canonicalization (query param stripping, tracking parameter removal) and SHA256 hashing.
  - 64-bit SimHash with Hamming distance deduplication for near-duplicate story detection.
  - Authenticated symmetric state encryption (`Fernet` AES-128-CBC + HMAC-SHA256) on orphan `state` git branch.
  - Telegram client with single-owner lock, rate limiting (<=1 msg/sec), 4096-char chunking, and HTML escaping.
- **Phase 2 (Scoring, Sectors, Routing)**:
  - Story clustering grouping multi-source reports and elevating primary items to the highest trust tier.
  - Multi-factor scoring engine: trust tier weights, linear recency decay (6 hours), cluster log boost, watchlist boost (+0.3), breaking keywords boost (+0.4), and penalty patterns.
  - Routing into breaking (>=0.75), digest (>=0.35), and discard (<0.35), with breaking overflow cap (max 8) and quiet hours hold.
- **Phase 3 (Extraction & Summarization)**:
  - Article text extractor with SSRF protection (`is_private_ip`), robots.txt checking, 2MB size cap, and HTML cleaning.
  - LLM summarizer provider abstraction supporting Google Gemini 1.5 Flash (primary) and Groq (fallback).
  - Strict output validator enforcing 2–4 bullet plain text summaries (~60 words, no URLs, no markdown bold/headers).
  - Summarize-only system prompt with prompt injection hardening and automatic degradation to RSS snippets.
- **Phase 4 (Digests & Commands)**:
  - Scheduled digest slots (`DIGEST_TIMES` in `TIMEZONE`) with 45-minute grace window and once-per-slot state flag.
  - Digest queue management in encrypted state and multi-sector digest message formatting.
  - Full suite of owner commands: `/help`, `/status`, `/sectors`, `/mute`, `/unmute`, `/watch add|remove`, `/watchlist`, `/digest`, `/pause`, `/resume`.
- **Phase 5 (Hardening & Ops)**:
  - Feed auto-disable after 5 consecutive failures with automated Telegram alert to owner.
  - LLM quota warning alerts at 80% daily capacity.
  - Atomic state branch history squashing via git plumbing (`git commit-tree` omitting `-p`).
  - Weekly keepalive workflow preventing automated schedule disablement.
  - Comprehensive operational documentation in `docs/RUNBOOK.md` and security audit in `docs/SECURITY.md`.
- **Phase 7 (Public Release Prep)**:
  - MIT License.
  - Root `README.md` with architecture, $0 caveats, quickstart, and fork guidance.
  - Step-by-step setup guide in `docs/SETUP.md`.
  - Security audit and threat model in `docs/SECURITY.md`.
