# Runbook

Operational procedures, monitoring guidelines, and troubleshooting for the Telegram News Bot.

---

## 1. System Overview

- **Runtime**: GitHub Actions scheduled workflow (`.github/workflows/run.yml`) running every 15 minutes with random start delay (0–180 seconds).
- **State Storage**: Orphan `state` git branch holding AES-128-CBC + HMAC-SHA256 authenticated ciphertext (`state.enc`).
- **Owner Security Lock**: Only messages matching `TELEGRAM_OWNER_CHAT_ID` are processed. All non-owner updates are dropped silently.
- **Cost**: $0. Standard GitHub Actions runners in public repositories are free and unlimited. Google Gemini free tier (15 RPM / 1,500 RPD) handles summarization with Groq fallback.

---

## 2. Telegram Commands Quick Reference

Send any of these commands to your bot directly in Telegram:

| Command | Action |
|---|---|
| `/status` | View operational health: active state, feed statuses, daily LLM token/call usage, queued digest items |
| `/sectors` | View all 5 sectors (`world`, `india`, `business`, `markets`, `crypto`) with active/muted badges |
| `/mute <sector>` | Suppress breaking alerts for a specific sector (e.g. `/mute crypto`) |
| `/unmute <sector>` | Re-enable breaking alerts for a sector (e.g. `/unmute crypto`) |
| `/watchlist` | Display all currently tracked ticker symbols and keywords |
| `/watch add <term>` | Add a keyword or stock/crypto ticker to your watchlist (e.g. `/watch add TSLA`) |
| `/watch remove <term>` | Remove a keyword from your watchlist |
| `/digest` | Request an immediate on-demand news digest |
| `/pause` | Temporarily suspend all outbound Telegram messages (state and dedupe tracking continue) |
| `/resume` | Resume normal news delivery |
| `/help` | Display command usage instructions and legal disclaimer |

---

## 3. Daily Health & Monitoring

### Checking Bot Health
1. Open your Telegram chat with the bot.
2. Send `/status`.
3. Check:
   - **Status**: Should be `Active ✅` (not paused).
   - **Last Run**: Should be within the last 15–30 minutes.
   - **Feeds Monitored**: Note if any feeds show failing counts.
   - **LLM Usage Today**: Confirm calls are within the 1,500 daily free tier limit.

### Inspecting Workflow Runs in GitHub Actions
1. Navigate to the repository's **Actions** tab on GitHub.
2. Select **News Bot Run**.
3. View the latest workflow run logs.
4. Verify:
   - Job completes with exit code 0 in ~30–90 seconds.
   - Log output contains only sanitized counts and statuses (no secrets, no article body text, no chat IDs).

---

## 4. Feed Rot & Auto-Disabling

Feeds that return errors (HTTP 4xx/5xx or timeout) increment an internal `consecutive_failures` counter in state.

- **Auto-Disable Threshold**: If a feed fails **5 consecutive times**, it is automatically disabled to prevent wasting pipeline time.
- **Telegram Notification**: When a feed is auto-disabled, the bot sends an alert:
  `⚠️ Feed Health Alert: Feed '<id>' failed 5 consecutive times and was automatically disabled.`
- **Troubleshooting**:
  1. Test the feed URL directly in your browser or run the validator:
     ```bash
     python scripts/feed_validator.py
     ```
  2. If the feed publisher changed their RSS endpoint:
     - Update the URL in `config/sources.yml` (or `config/sources.local.yml`).
     - Commit and push to `main`.
  3. Once the feed returns HTTP 200, the failure counter resets automatically.

---

## 5. LLM Quota & Fallbacks

- **Quota Protection**: State tracks `calls_today` and `tokens_today`.
- **Automatic Fallback Chain**:
  1. **Primary**: Google Gemini 1.5 Flash (free tier: 15 RPM, 1,500 RPD).
  2. **Secondary Fallback**: Groq (if `GROQ_API_KEY` configured).
  3. **Tertiary Degradation**: RSS snippet fallback. If both LLM quotas are exhausted, the pipeline never crashes; it delivers the original RSS summary snippet with `[RSS snippet]` marker.
- **80% Alert**: When daily usage hits 80% (1,200 calls or 400,000 tokens), the bot sends a budget alert to the owner.

---

## 6. State Branch Management & Squashing

### Automatic Squashing
`StateManager` automatically squashes the commit history of the orphan `state` branch whenever the commit count exceeds 50 commits. This keeps the branch to a single commit, preventing repository bloat.

### Manual Squashing
To manually squash the state branch at any time:
```bash
export STATE_ENCRYPTION_KEY="your-base64-key"
python scripts/squash_state.py
git push origin state --force
```

### State Recovery / Key Loss
- If you lose your `STATE_ENCRYPTION_KEY`:
  1. The bot will be unable to decrypt prior state.
  2. Generate a new key:
     ```bash
     python scripts/generate_state_key.py
     ```
  3. Update the `STATE_ENCRYPTION_KEY` secret in your repository's `production` environment.
  4. Reset the state branch:
     ```bash
     git push origin --delete state
     ```
  5. The bot will automatically initialize a fresh encrypted state branch on the next run.

---

## 7. Emergency Procedures

### Suspend Outbound Alerts
Send `/pause` to the bot in Telegram. Delivery of breaking news and scheduled digests will stop immediately while the bot continues updating seen hashes in the background.

### Resume Delivery
Send `/resume` to the bot in Telegram.

### Force Dry-Run Execution
Trigger the workflow manually with dry-run enabled:
1. Go to **Actions** -> **News Bot Run** -> **Run workflow**.
2. Keep the `dry_run` checkbox checked (`true`).
3. Click **Run workflow**.
