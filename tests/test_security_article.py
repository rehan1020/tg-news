"""Security tests: Assert that untrusted article text and summaries NEVER reach state or logs."""

from __future__ import annotations

import io
import logging

import pytest
import respx

from src.bot.logger import setup_logging
from src.bot.runner import run
from src.state.manager import BotState

SENSITIVE_ARTICLE_TEXT = "SECRET_CANARY_ARTICLE_TEXT_XYZ_123456789_CONFIDENTIAL"
SENSITIVE_ARTICLE_TITLE = "CANARY_TITLE_ABC_987654321"


@pytest.mark.asyncio
@respx.mock
async def test_no_article_text_in_state_or_logs(mock_env, tmp_path):
    """Article text and titles must never be stored in state JSON or emitted in logs."""
    # Capture log stream
    stream = io.StringIO()
    setup_logging()
    root = logging.getLogger()
    for h in root.handlers:
        h.stream = stream

    # Mock RSS feed returning sensitive canary article text
    respx.get(url__startswith="https://feeds.bbci.co.uk").respond(
        status_code=200,
        text=f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>BBC News</title>
            <item>
              <title>{SENSITIVE_ARTICLE_TITLE}</title>
              <link>https://example.com/canary-article</link>
              <description>{SENSITIVE_ARTICLE_TEXT}</description>
              <pubDate>Mon, 17 Oct 2026 12:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """,
    )

    # Mock all other feeds with empty RSS to isolate test
    respx.get(url__startswith="https://").respond(
        status_code=200, text="<rss><channel></channel></rss>"
    )

    # Execute run in dry-run mode
    await run(dry_run=True)

    log_output = stream.getvalue()

    # 1. Assert canary article text NEVER appears in log output
    assert SENSITIVE_ARTICLE_TEXT not in log_output
    assert SENSITIVE_ARTICLE_TITLE not in log_output

    # 2. Assert state schema NEVER contains article text or titles
    state = BotState()
    serialized_state = state.to_json()

    assert SENSITIVE_ARTICLE_TEXT not in serialized_state
    assert SENSITIVE_ARTICLE_TITLE not in serialized_state
    assert "articles" not in serialized_state
    assert "article_text" not in serialized_state
    assert "titles" not in serialized_state
