"""Tests for Telegram client, HTML escaping, and owner lock."""

from __future__ import annotations

import time

import pytest
import respx

from src.feeds.models import FeedItem
from src.state.manager import BotState
from src.telegram.client import TelegramClient, format_headline_message, format_relative_time


def _create_sample_item() -> FeedItem:
    return FeedItem(
        id="sample_hash_123",
        title="Breaking: Central Bank Announces Policy Change <Important> & Urgent",
        url="https://example.com/breaking?id=1&ref=news",
        canonical_url="https://example.com/breaking?id=1",
        source_id="reuters",
        source_name="Reuters & Associates",
        sector="business",
        trust_tier="official",
        published_at=time.time() - 300,  # 5 min ago
    )


def test_format_headline_escapes_html():
    item = _create_sample_item()
    msg = format_headline_message(item)

    # HTML special chars must be escaped in content
    assert "<Important>" not in msg
    assert "&lt;Important&gt;" in msg
    assert "Reuters &amp; Associates" in msg
    assert "<b>💼 #BUSINESS</b>" in msg
    assert '<a href="https://example.com/breaking?id=1">Read original</a>' in msg


def test_format_relative_time():
    now = time.time()
    assert format_relative_time(now - 30) == "just now"
    assert format_relative_time(now - 120) == "2m ago"
    assert format_relative_time(now - 7200) == "2h ago"
    assert format_relative_time(now - 100000) == "1d ago"


def test_chunk_message_boundaries():
    short = "Hello World"
    assert TelegramClient._chunk_message(short, 100) == [short]

    p1 = "A" * 50
    p2 = "B" * 50
    text = f"{p1}\n\n{p2}"
    chunks = TelegramClient._chunk_message(text, 60)
    assert len(chunks) == 2
    assert chunks[0] == p1
    assert chunks[1] == p2


@pytest.mark.asyncio
async def test_telegram_dry_run():
    client = TelegramClient(
        bot_token="mock",
        owner_chat_id="999888777",
        dry_run=True,
    )
    # Dry run should succeed without network calls
    success = await client.send_message("Test message")
    assert success is True

    updates = await client.get_owner_updates(BotState())
    assert updates == []


@pytest.mark.asyncio
@respx.mock
async def test_owner_lock_ignores_non_owner():
    owner_id = "12345"
    client = TelegramClient(
        bot_token="mock",
        owner_chat_id=owner_id,
        dry_run=False,
    )

    # Mock Telegram getUpdates returning 2 messages: 1 from stranger, 1 from owner
    respx.get(url__startswith="https://api.telegram.org/botmock/getUpdates").respond(
        status_code=200,
        json={
            "ok": True,
            "result": [
                {
                    "update_id": 101,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 99999},  # Stranger chat id
                        "from": {"id": 99999},
                        "text": "/help",
                    },
                },
                {
                    "update_id": 102,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 12345},  # Valid owner
                        "from": {"id": 12345},
                        "text": "/status",
                    },
                },
            ],
        },
    )

    state = BotState()
    owner_updates = await client.get_owner_updates(state)

    assert len(owner_updates) == 1
    assert owner_updates[0]["update_id"] == 102
    assert state.telegram_update_offset == 103
