# Assumptions

This document records assumptions made during development that should be verified.

## Phase 0

- **GitHub Actions cron jitter**: GitHub Actions cron schedules have 5-15 minute jitter.
  The bot is designed to be idempotent across runs.
- **Public repo unlimited minutes**: Public repositories get unlimited GitHub Actions
  minutes on standard runners (ubuntu-latest). Verified against
  [GitHub docs](https://docs.github.com/en/billing/managing-billing-for-github-actions/about-billing-for-github-actions).
- **Keepalive mechanism**: GitHub disables scheduled workflows after 60 days of repo
  inactivity. A weekly empty commit prevents this. To be verified against current docs.
- **Python 3.12**: Targeted runtime version in GitHub Actions. Local development may
  use 3.12+.

## Phase 1 — Feed Verification (2026-10-17)

All feed candidates in `config/sources.yml` were live-tested using `scripts/feed_validator.py`.
- **Enabled & Verified Live (HTTP 200)**:
  - World: BBC World, Al Jazeera, DW News, The Guardian, NYT Top Stories
  - India: The Hindu, Indian Express, Mint, Economic Times
  - Business / Macro: Federal Reserve Press, ECB Press, RBI Press (`https://rbi.org.in/pressreleases_rss.xml`), SEBI Press (`https://www.sebi.gov.in/sebirss.xml`)
  - Markets: Yahoo Finance S&P 500 (`https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC`)
  - Crypto: CoinDesk, Cointelegraph, The Block
- **Disabled Feeds & Rationale**:
  - `pib` (Press Information Bureau): PIB WAF blocks non-browser custom User-Agents with HTTP 403. Disabled by default to strictly adhere to automated crawler etiquette.
  - `imf_news`: IMF website requires a client-side JavaScript challenge/redirect; direct RSS returned 0 entries. Disabled by default.
  - `gdelt` & `google_news`: Aggregators disabled by default per upstream policy pending adopter preference.
  - `alphavantage` & `cryptopanic`: Disabled by default; require optional user API keys.
