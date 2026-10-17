# Setup & Deployment Guide

This guide walks through configuring and running your own private instance of the Telegram News Bot in under 10 minutes at $0 cost.

---

## 1. Prerequisites

- A **GitHub account** (free tier; public repositories receive unlimited Actions runner minutes).
- A **Telegram account**.
- A **Google AI Studio API key** (free tier; billing kept disabled).

---

## 2. Step 1: Create Your Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather).
2. Send `/newbot`. Follow the prompts to choose a display name and unique username ending in `bot` (e.g. `my_news_feed_bot`).
3. BotFather will provide your **HTTP API Token** (e.g. `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`).
   - Save this as `TELEGRAM_BOT_TOKEN`.
4. **Harden Group Settings**:
   - Send `/setjoingroups` to BotFather.
   - Select your bot and choose **Disable** (guarantees the bot cannot be added to group chats).
5. **Get Your Telegram Owner Chat ID**:
   - Open your newly created bot in Telegram and click **Start** (or send `/start`).
   - Message [@userinfobot](https://t.me/userinfobot) or open in your browser:
     ```
     https://api.telegram.org/bot<YOUR_TELEGRAM_BOT_TOKEN>/getUpdates
     ```
   - Look for `"chat":{"id": 123456789}` in the JSON response.
   - Save this numerical ID as `TELEGRAM_OWNER_CHAT_ID`.

---

## 3. Step 2: Obtain LLM Summarizer API Keys

### Primary Summarizer: Google Gemini (Free Tier)
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Sign in with your Google account.
3. Click **Get API key** -> **Create API key**.
4. Copy the API key and save as `GEMINI_API_KEY`.
   > [!IMPORTANT]
   > Do **NOT** enable billing or attach a credit card to your Google Cloud project. The free tier gives 15 requests per minute and 1,500 requests per day, which is more than enough for a private news bot.

### Fallback Summarizer: Groq (Recommended Free Tier)
1. Go to [Groq Console](https://console.groq.com/).
2. Sign up / sign in and navigate to **API Keys**.
3. Create an API key and save as `GROQ_API_KEY`.

---

## 4. Step 3: Generate State Encryption Key

Because state is stored on a public git branch, all state files must be symmetrically encrypted before commit.

Run the provided key generator locally:
```bash
python scripts/generate_state_key.py
```
This generates a 256-bit URL-safe base64 encryption key:
```
dGVzdC1lbmNyeXB0aW9uLWtleS0xMjM0NTY3ODkwYWJj
```
Save this string as `STATE_ENCRYPTION_KEY`. Store a backup copy in your password manager.

---

## 5. Step 4: Create Your Repo and Configure Secrets

1. In the upstream repository, click **Use this template** (or click **Fork**).
2. Choose **Public** visibility (public repositories receive unlimited free standard GitHub Actions minutes; private repositories are limited to ~2,000 minutes/month).
3. In your new repository, navigate to:
   **Settings** -> **Environments** -> **New environment**
   - Name the environment: `production`
   - Under **Deployment branches and tags**, select **Selected branches** -> add `main`.
4. Under **Environment secrets**, add the following required secrets:

| Secret Name | Required | Example / Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Token from @BotFather |
| `TELEGRAM_OWNER_CHAT_ID` | Yes | Your numerical Telegram user ID |
| `STATE_ENCRYPTION_KEY` | Yes | 256-bit base64 key generated in Step 3 |
| `GEMINI_API_KEY` | Yes | Google AI Studio API key |
| `GROQ_API_KEY` | Recommended | Groq API key for failover redundancy |
| `WATCHLIST` | Optional | Comma-separated list: `AAPL,BTC,TSLA,semiconductors` |
| `DIGEST_TIMES` | Optional | Comma-separated 24h slots: `08:00,18:00` |
| `QUIET_HOURS` | Optional | Local hold range: `23:00-06:00` |
| `TIMEZONE` | Optional | IANA timezone name: `UTC`, `Asia/Kolkata`, `America/New_York` |

---

## 6. Step 5: Desynchronize Cron Schedule

To prevent thousands of forks from polling feed servers and LLM endpoints at the exact same minute:
1. Open `.github/workflows/run.yml` in your repository.
2. Edit the `cron` line under `schedule`:
   ```yaml
   on:
     schedule:
       # Pick your own random off-peak minutes!
       # Example: instead of 7,22,37,52 use 11,26,41,56
       - cron: "11,26,41,56 * * * *"
   ```
3. Commit the change directly to `main`.

---

## 7. Step 6: Enable Actions and Run First Test

1. Navigate to the **Actions** tab in your repository.
2. Click **"I understand my workflows, go ahead and enable them"** (GitHub disables scheduled workflows in newly created forks by default).
3. In the left sidebar, click **News Bot Run**.
4. Click **Run workflow**:
   - Leave `dry_run` checked (`true`).
   - Click **Run workflow**.
5. Inspect the execution logs. Once the dry run succeeds with exit code 0, trigger the workflow with `dry_run: false`.
6. Open Telegram: your bot will send you your first news alerts!
