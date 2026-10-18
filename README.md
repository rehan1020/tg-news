# Telegram News Bot

A private, single-user Telegram news bot delivering trusted, multi-sector news at **$0 cost** running entirely on **GitHub Actions** in a public repository. Zero servers. Zero paid API tiers.

---

> [!IMPORTANT]
> **No Warranty & Not Financial Advice**: This project is provided "as is", without warranty of any kind. All market, business, and crypto news delivered by this bot is aggregated for informational purposes only. It does **not** constitute financial, investment, legal, or trading advice.

> [!NOTE]
> **No Pull Requests / Shared As-Is**: This project does **not** accept pull requests, feature requests, or issues. It is provided as-is for you to fork, copy, and run your own independent instance.

---

## 1. What It Is and Is Not

- **What it is**:
  - A serverless news assistant that polls verified RSS feeds across 5 sectors: World/Geopolitics, India National, Business/Macro, Markets, and Crypto.
  - Symmetrically encrypted state stored on an orphan `state` git branch with authenticated ciphertext (`Fernet` AES-128-CBC + HMAC-SHA256).
  - Multi-tier summarization using free-tier LLMs (Gemini 1.5 Flash primary with Groq failover and RSS snippet degradation).
  - Single-owner security lock: ignores all messages from anyone other than your Telegram user ID.
  - Scheduled daily digests, quiet hours protection, story clustering, and on-demand Telegram commands (`/status`, `/sectors`, `/mute`, `/watch`, `/digest`, `/pause`).

- **What it is not**:
  - A multi-user hosted service.
  - A trading signal bot or automated financial advisor.
  - A web-scraping republisher (delivers brief 2–4 bullet takeaways with links to original publishers).

---

## 2. $0 Cost Architecture & Guarantees

| Platform | Tier | Limit | Usage in this Bot |
|---|---|---|---|
| **GitHub Actions** | Public Repo | Unlimited minutes on standard Ubuntu runners | ~15 min cron runs taking ~45s each |
| **Google Gemini** | Free Tier (AI Studio) | 15 RPM / 1,500 requests per day | ~20–60 calls/day; billing disabled |
| **Groq** | Free Tier | 30 RPM fallback | Automatic failover only |
| **Telegram Bot API** | Free | 30 msg/sec | Strictly throttled to <=1 msg/sec |

---

## 3. Fork Visibility Warning

- **Public Repositories**: Public forks of this template repository get **unlimited free GitHub Actions minutes**. State is encrypted on an orphan git branch, secrets live in GitHub Environments, and all logs are scrubbed by a central redacting logger.
- **Private Repositories**: If you make your fork private, GitHub limits free accounts to ~2,000 runner minutes per month. A 15-minute cron will consume ~3,000 minutes per month, which exceeds the private limit. **We strongly recommend keeping your fork public.**

---

## 4. 10-Minute Quickstart

1. **Create your Telegram bot**: Message [@BotFather](https://t.me/botfather) in Telegram -> `/newbot`. Note your `TELEGRAM_BOT_TOKEN`. Disable groups via `/setjoingroups`.
2. **Get your chat ID**: Message your bot `/start`, then check [@userinfobot](https://t.me/userinfobot) to get your numerical user ID (`TELEGRAM_OWNER_CHAT_ID`).
3. **Get a free Gemini API key**: Create a free API key at [Google AI Studio](https://aistudio.google.com) (`GEMINI_API_KEY`). Keep billing disabled.
4. **Generate your state encryption key**:
   ```bash
   python scripts/generate_state_key.py
   ```
5. **Create your repository**:
   - Click **Use this template** (or **Fork**).
   - In **Settings** -> **Environments**, create an environment named `production` restricted to the `main` branch.
   - Add environment secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_CHAT_ID`, `STATE_ENCRYPTION_KEY`, and `GEMINI_API_KEY`.
6. **Desynchronize your schedule**: Edit `.github/workflows/run.yml` and change the cron minute to your own off-peak numbers (e.g. `14,29,44,59 * * * *`). Do NOT use `:00` or `:30`.
7. **Enable Actions**: In your fork's **Actions** tab, click **"I understand my workflows, go ahead and enable them"**. Run manually to verify.

For detailed step-by-step instructions with optional API keys and private configuration variables, see [docs/SETUP.md](docs/SETUP.md).

---

## 5. Telegram Commands

Interact directly with your bot using these owner commands:

- `/status` — View uptime, feed statuses, LLM quota consumption, and queued digest count.
- `/crypto [term]` — On-demand crypto & day-trading intelligence (e.g. `/crypto` or `/crypto btc`).
- `/markets` — On-demand stock market & day-trading movers.
- `/digest` — Request an immediate, on-demand curated news digest across all sectors.
- `/sectors` — Toggle or inspect active sectors (`world`, `india`, `business`, `markets`, `crypto`).
- `/mute <sector>` / `/unmute <sector>` — Suppress or restore alerts for any sector.
- `/watchlist` — View current watchlist keywords and stock/crypto tickers.
- `/watch add <term>` / `/watch remove <term>` — Dynamically modify watchlist terms.
- `/pause` / `/resume` — Pause or resume alert delivery.
- `/help` — View full command list and disclaimers.

---

## 6. Security & Operational Documentation

- [Setup Guide](docs/SETUP.md) — Step-by-step API key generation and GitHub environment configuration.
- [Operational Runbook](docs/RUNBOOK.md) — Day-to-day operations, feed health troubleshooting, and state recovery.
- [Security Architecture](docs/SECURITY.md) — Threat model, redaction invariants, SSRF guards, and private vulnerability reporting.
- [Assumptions Log](docs/ASSUMPTIONS.md) — Verified technical assumptions, feed audit findings, and keepalive specifications.
- [Changelog](docs/CHANGELOG.md) — Detailed version and phase implementation history.

---

## 7. License

Distributed under the [MIT License](LICENSE).
