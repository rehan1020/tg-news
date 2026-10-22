/**
 * Cloudflare Worker for Telegram News Bot
 *
 * Provides:
 * 1. Instant Telegram Webhook responder (< 1 second)
 * 2. Instant GitHub Actions runner dispatch for heavy commands (/digest, /markets, /crypto)
 * 3. Exact 15-minute scheduled cron runner (bypasses GitHub Actions cron throttling)
 *
 * Environment variables required in Cloudflare Worker:
 * - TELEGRAM_BOT_TOKEN: Your Telegram bot token from @BotFather
 * - TELEGRAM_OWNER_CHAT_ID: Your personal numeric Telegram user/chat ID
 * - GITHUB_PAT: GitHub Personal Access Token (classic with 'repo' scope or fine-grained with Actions:write)
 * - GITHUB_REPO: "rehan1020/tg-news" (or your repo name)
 * - WEBHOOK_SECRET: (Optional) Secret token for setWebhook validation
 */

const HELP_MESSAGE = `🤖 <b>Telegram News Bot Commands</b>

• /status — Current bot operational status and LLM usage
• /world [term] — On-demand world & geopolitical news (aliases: /geopolitics, /global)
• /india [term] — On-demand India & national news (alias: /national)
• /crypto [term] — On-demand crypto & day-trading market news
• /markets [term] — On-demand business & market news (aliases: /business, /finance)
• /digest — Request an immediate full daily news digest
• /sectors — View sectors and their active/muted status
• /mute &lt;sector&gt; — Mute news alerts for a sector
• /unmute &lt;sector&gt; — Unmute news alerts for a sector
• /watchlist — View active watchlist keywords
• /watch add &lt;term&gt; — Add a term or ticker to watchlist
• /watch remove &lt;term&gt; — Remove a term from watchlist
• /pause — Pause delivery of breaking alerts and digests
• /resume — Resume news delivery
• /help — Show this help message

⚠️ <b>Notice</b>: This bot provides automated news aggregation for informational purposes only. It does not provide financial, investment, or trading advice. No warranty of any kind is provided.`;

export default {
  /**
   * HTTP Webhook Handler (receives Telegram updates)
   */
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Telegram News Bot Webhook is running. Send POST updates from Telegram.", {
        status: 200,
        headers: { "Content-Type": "text/plain" },
      });
    }

    // Optional secret token verification
    if (env.WEBHOOK_SECRET) {
      const token = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
      if (token !== env.WEBHOOK_SECRET) {
        return new Response("Unauthorized", { status: 403 });
      }
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    const message = update.message || update.channel_post;
    if (!message || !message.text) {
      return new Response("OK", { status: 200 });
    }

    const chatId = String(message.chat?.id || "");
    const fromId = String(message.from?.id || "");
    const ownerId = String(env.TELEGRAM_OWNER_CHAT_ID || "").trim();

    // Security lock: Ignore messages from anyone other than the configured owner
    if (chatId !== ownerId && fromId !== ownerId) {
      console.warn(`Dropped unauthorized message from chat ${chatId} (expected ${ownerId})`);
      return new Response("OK", { status: 200 });
    }

    const text = message.text.trim();
    if (!text.startsWith("/")) {
      return new Response("OK", { status: 200 });
    }

    // Split command and argument
    const parts = text.split(/\s+/);
    const cmd = parts[0].toLowerCase().split("@")[0]; // remove bot mention if present
    const args = parts.slice(1).join(" ").trim();

    const repo = env.GITHUB_REPO || "rehan1020/tg-news";

    // Instant responses (no GitHub Action needed)
    if (cmd === "/help" || cmd === "/start") {
      await sendTelegram(env.TELEGRAM_BOT_TOKEN, ownerId, HELP_MESSAGE);
      return new Response("OK", { status: 200 });
    }

    if (cmd === "/ping") {
      await sendTelegram(env.TELEGRAM_BOT_TOKEN, ownerId, "🏓 <b>Pong!</b> Cloudflare Worker is active and online.");
      return new Response("OK", { status: 200 });
    }

    // Commands requiring pipeline processing (dispatch to GitHub Actions)
    let replyNotice = "";
    let clientPayload = { command: text };

    if (cmd === "/digest") {
      replyNotice = "📰 <b>Daily Digest requested!</b>\n\nCompiling stories across all active sectors. Delivering in ~25 seconds...";
      clientPayload.force_digest = true;
    } else if (["/world", "/geopolitics", "/global"].includes(cmd)) {
      const filterStr = args ? ` (filtered by: <code>${escapeHtml(args)}</code>)` : "";
      replyNotice = `🌍 <b>World & Geopolitical Intelligence requested!</b>${filterStr}\n\nScanning BBC, Al Jazeera, DW, Guardian, France 24, Euronews, Politico, UN News, and NPR. Delivering in ~25 seconds...`;
      clientPayload.world_news = true;
    } else if (["/india", "/national"].includes(cmd)) {
      const filterStr = args ? ` (filtered by: <code>${escapeHtml(args)}</code>)` : "";
      replyNotice = `🇮🇳 <b>India & National News Intelligence requested!</b>${filterStr}\n\nScanning The Hindu, Hindustan Times, Times of India, News18, NDTV, and Mint. Delivering in ~25 seconds...`;
      clientPayload.india_news = true;
    } else if (["/markets", "/business", "/finance", "/macro"].includes(cmd)) {
      const filterStr = args ? ` (filtered by: <code>${escapeHtml(args)}</code>)` : "";
      replyNotice = `📈 <b>Business & Market Intelligence requested!</b>${filterStr}\n\nScanning CNBC, WSJ, MarketWatch, Fortune, Mint, ET, and central banks. Delivering in ~25 seconds...`;
      clientPayload.markets_news = true;
    } else if (cmd === "/crypto") {
      const filterStr = args ? ` (filtered by: <code>${escapeHtml(args)}</code>)` : "";
      replyNotice = `🪙 <b>Crypto Intelligence requested!</b>${filterStr}\n\nScanning CoinDesk, Cointelegraph, The Block, and market sources. Delivering in ~25 seconds...`;
      clientPayload.crypto_news = true;
    } else {
      replyNotice = `⚡ <b>Executing command:</b> <code>${escapeHtml(text)}</code>\n\nProcessing update via GitHub Actions runner...`;
    }

    // Send immediate confirmation to Telegram
    await sendTelegram(env.TELEGRAM_BOT_TOKEN, ownerId, replyNotice);

    // Dispatch GitHub Actions run
    ctx.waitUntil(dispatchGitHub(env.GITHUB_PAT, repo, "telegram_command", clientPayload));

    return new Response("OK", { status: 200 });
  },

  /**
   * Cloudflare Cron Trigger (Scheduled Polling every 15 min)
   * Bypasses GitHub's delayed cron scheduler
   */
  async scheduled(event, env, ctx) {
    const repo = env.GITHUB_REPO || "rehan1020/tg-news";
    console.log(`Cloudflare Cron Trigger fired at ${new Date().toISOString()}; dispatching news_run to GitHub Actions.`);
    await dispatchGitHub(env.GITHUB_PAT, repo, "news_run", {});
  },
};

/**
 * Send an HTML formatted message to Telegram
 */
async function sendTelegram(botToken, chatId, htmlText) {
  if (!botToken || !chatId) return;
  try {
    const url = `https://api.telegram.org/bot${botToken}/sendMessage`;
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: htmlText,
        parse_mode: "HTML",
        disable_web_page_preview: true,
      }),
    });
  } catch (err) {
    console.error("Failed to send Telegram message:", err);
  }
}

/**
 * Trigger GitHub Actions via repository_dispatch API
 */
async function dispatchGitHub(pat, repo, eventType, clientPayload) {
  if (!pat) {
    console.error("Missing GITHUB_PAT secret; cannot trigger GitHub Action");
    return;
  }
  const url = `https://api.github.com/repos/${repo}/dispatches`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${pat}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "Cloudflare-Worker-NewsBot",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        event_type: eventType,
        client_payload: clientPayload,
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error(`GitHub dispatch failed with ${res.status}: ${errText}`);
    } else {
      console.log(`Successfully dispatched '${eventType}' to ${repo}`);
    }
  } catch (err) {
    console.error("Error dispatching to GitHub:", err);
  }
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
