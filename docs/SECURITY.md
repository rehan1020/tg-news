# Security Architecture & Threat Model

This document outlines the security architecture, threat model, and mitigations implemented in the Telegram News Bot.

---

## 1. Threat Model for Public Repositories

Because this repository runs publicly on GitHub Actions, the primary threats and architectural defenses are:

| Threat | Risk | Architectural Mitigation |
|---|---|---|
| **Secret Exfiltration via Logs** | High | Central `RedactingFilter` intercepts and redacts known secrets, token patterns, and query params from all log records. Logs contain counts and statuses only (no article text, summaries, or chat IDs). |
| **State Tampering or Leakage** | High | State is stored on an orphan `state` branch strictly as authenticated ciphertext (`Fernet` AES-128-CBC + HMAC-SHA256). Seen items store only SHA256 hashes and epoch timestamps. |
| **Prompt Injection via News Articles** | High | News articles and feed content are treated as untrusted data. The LLM prompt is summarize-only with explicit instructions to ignore embedded commands. LLM output triggers zero actions, is validated against strict constraints, and is HTML-escaped. |
| **Server-Side Request Forgery (SSRF)** | Medium | Outbound article extractor blocks private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`), link-local, and cloud metadata endpoints (`169.254.169.254`). |
| **Unauthorized Bot Interaction** | Medium | Single-owner lock in `TelegramClient`: silently ignores and drops any update whose chat ID or sender ID does not match `TELEGRAM_OWNER_CHAT_ID`. Never replies to non-owners. |
| **Supply Chain / Malicious Actions** | Medium | All third-party GitHub Actions are pinned to full immutable commit SHAs. Dependencies in `requirements.txt` are pinned to exact versions. |
| **Fork PR Workflow Exploits** | High | Default repository workflow permissions are read-only. CI runs without secrets. Workflows requiring secrets run only on `main` in the `production` environment. |

---

## 2. Security Invariants (Section 12 Verification)

Each requirement from Section 12 of the project specification has been audited and verified:

1. **GitHub Environment Secrets**:
   - Secrets are configured solely inside GitHub Environments (`production`), restricted to the `main` branch.
   - Secrets are injected as environment variables only into the single `run` job step that executes Python.
2. **Minimal Workflow Permissions**:
   - CI workflow permissions are locked to `contents: read`.
   - `run.yml` and `keepalive.yml` specify only `contents: write` for updating state/keepalive refs.
3. **No `pull_request_target`**:
   - Only standard `push` and `pull_request` events are used. Fork PRs have no access to repository secrets or environment variables.
4. **Action SHA Pinning**:
   - `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683` (v4)
   - `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` (v5)
5. **Central Redacting Logger**:
   - `src/bot/logger.py` enforces regex and literal redaction across messages and object arguments.
   - Tested under `tests/test_logger.py`, `tests/test_security.py`, and `tests/test_dry_run.py`.
6. **Sanitized Run Summaries**:
   - Log output emits structured metrics (`raw_items`, `breaking_count`, `sent_messages`, `digest_sent`).
   - Plaintext article text, titles, summaries, and chat IDs are never logged.
7. **SSRF and Egress Protection**:
   - `src/extract/extractor.py` uses `ipaddress.is_private` to block non-routable destination hosts.
8. **Outbound Host Allowlist**:
   - `scripts/check_hosts.py` validates that all outbound connections are restricted to approved LLM APIs, Telegram API, and configured news domains. Tested in CI via `tests/test_check_hosts.py`.
9. **Encrypted State Round-Trip**:
   - Verified via `tests/test_state.py`: tampering with ciphertext raises `InvalidToken`; plaintext state is never committed.

---

## 3. Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it privately via GitHub's [Private Security Advisories](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability).

**Please do NOT open a public issue for security-related matters.**
