# Cloudflare Worker for Telegram News Bot

This Cloudflare Worker provides **instant Telegram command responses** and triggers the news pipeline in **~20 seconds**, solving the multi-hour GitHub Actions cron delay.

---

## What It Does
1. **Sub-second Replies**: When you type `/help`, `/ping`, etc., it replies instantly.
2. **Instant Heavy News Dispatch**: When you type `/digest`, `/markets`, or `/crypto`, it immediately acknowledges your request in Telegram, and triggers GitHub Actions via the `repository_dispatch` API. GitHub starts running within seconds and delivers your news report in ~20-30 seconds.
3. **Exact 15-Minute News Polling**: Its built-in Cron Trigger (`*/15 * * * *`) fires on the minute, bypassing GitHub Actions' delayed internal cron scheduler.

---

## Quick Setup (2 Minutes via Cloudflare Dashboard)

### Step 1: Create a GitHub Personal Access Token (PAT)
1. In GitHub, go to **Settings** → **Developer Settings** → **Personal Access Tokens** → **Tokens (classic)** (or Fine-grained tokens).
2. Click **Generate new token**.
3. Name: `tg-news-cloudflare`
4. Scope: select `repo` (or for fine-grained: Repository permissions → **Actions**: Read and Write).
5. Generate and copy the token.

### Step 2: Deploy the Cloudflare Worker (100% Free)
1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) and log in.
2. In the left sidebar, click **Compute (Workers) & Pages** → **Create application** → **Create Worker**.
3. Name it `tg-news-relay` and click **Deploy**.
4. Click **Edit code**, delete any existing sample code, and paste the entire contents of [`cloudflare/worker.js`](./worker.js).
5. Click **Deploy** in the top right.

### Step 3: Add Variables and Secrets
1. In your Worker's dashboard, go to **Settings** → **Variables and Secrets**.
2. Under **Secrets**, click **Add** for each:
   - `TELEGRAM_BOT_TOKEN`: Your bot token from @BotFather.
   - `TELEGRAM_OWNER_CHAT_ID`: Your personal numeric Telegram chat/user ID.
   - `GITHUB_PAT`: The token you created in Step 1.
   - `GITHUB_REPO`: `rehan1020/tg-news` (or your repository path).

### Step 4: Add Scheduled Cron Trigger (Optional but Recommended)
1. In your Worker's dashboard, go to **Settings** → **Triggers**.
2. Under **Cron Triggers**, click **Add Cron Trigger**.
3. Set the cron expression: `*/15 * * * *` (runs every 15 minutes).
4. Click **Add Trigger**.

### Step 5: Register the Webhook with Telegram
Copy your Worker's URL (e.g. `https://tg-news-relay.<subdomain>.workers.dev`).

In your browser or terminal (replace with your actual bot token and worker URL):
```
https://api.telegram.org/bot<YOUR_TELEGRAM_BOT_TOKEN>/setWebhook?url=https://tg-news-relay.<YOUR_SUBDOMAIN>.workers.dev
```
You should see:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

---

## Testing
Open your bot in Telegram:
1. Send `/ping` → Replies **instantly** (`🏓 Pong! Cloudflare Worker is active and online.`).
2. Send `/help` → Replies **instantly** with the full command guide.
3. Send `/markets` or `/digest` → Acknowledges immediately, triggers GitHub Actions, and delivers the full report in ~25 seconds.
