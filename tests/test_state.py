"""Tests for StateManager and encrypted BotState."""

from __future__ import annotations

import base64
import json
import secrets
import time

import pytest

from src.state.manager import BotState, StateManager


@pytest.fixture
def test_key():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def test_state_encrypt_decrypt_round_trip(test_key):
    mgr = StateManager(encryption_key=test_key)
    plaintext = '{"hello": "world", "val": 123}'
    ciphertext = mgr.encrypt(plaintext)
    assert ciphertext != plaintext.encode("utf-8")
    assert mgr.decrypt(ciphertext) == plaintext


def test_invalid_key_fails(test_key):
    mgr1 = StateManager(encryption_key=test_key)
    other_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    mgr2 = StateManager(encryption_key=other_key)

    ciphertext = mgr1.encrypt("confidential")
    with pytest.raises(ValueError, match="Failed to decrypt state"):
        mgr2.decrypt(ciphertext)


def test_tampered_ciphertext_fails(test_key):
    mgr = StateManager(encryption_key=test_key)
    ciphertext = bytearray(mgr.encrypt("data"))
    # Flip a bit
    ciphertext[20] ^= 0xFF
    with pytest.raises(ValueError, match="Failed to decrypt state"):
        mgr.decrypt(bytes(ciphertext))


def test_state_json_contains_no_plaintext_titles():
    state = BotState()
    h = "a" * 64
    state.seen_hashes[h] = time.time()
    raw = state.to_json()
    parsed = json.loads(raw)

    assert "seen_hashes" in parsed
    assert h in parsed["seen_hashes"]
    # Verify no title or article fields exist in the schema
    assert "titles" not in parsed
    assert "articles" not in parsed
    assert "text" not in parsed


def test_prune_retention():
    state = BotState()
    now = time.time()
    old_ts = now - (15 * 86400)  # 15 days ago (expired)
    fresh_ts = now - (2 * 86400)  # 2 days ago (valid)

    state.seen_hashes["old_hash"] = old_ts
    state.seen_hashes["fresh_hash"] = fresh_ts
    state.seen_simhashes["12345"] = old_ts
    state.seen_simhashes["67890"] = fresh_ts

    state.prune_retention(retention_seconds=14 * 86400)

    assert "old_hash" not in state.seen_hashes
    assert "fresh_hash" in state.seen_hashes
    assert "12345" not in state.seen_simhashes
    assert "67890" in state.seen_simhashes


def test_schema_version_check():
    future_state = json.dumps({"schema_version": 999})
    with pytest.raises(ValueError, match="is newer than supported"):
        BotState.from_json(future_state)


def test_dry_run_state_manager(test_key):
    mgr = StateManager(encryption_key=test_key, dry_run=True)
    state = mgr.load_state()
    assert isinstance(state, BotState)
    # Save in dry-run should not raise and should not write files
    mgr.save_state(state)
