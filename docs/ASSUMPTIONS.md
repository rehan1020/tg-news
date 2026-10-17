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

## Feed URLs

Feed URLs in `config/sources.yml` are candidates. Each will be live-verified in Phase 1.
URLs marked with "to be verified" notes are best-effort and may need correction.
