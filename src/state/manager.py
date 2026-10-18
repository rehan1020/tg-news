"""Encrypted state manager for orphan `state` git branch.

Security invariants:
- Plaintext state is NEVER committed to git, NEVER logged, and NEVER uploaded as an artifact.
- State contains ONLY authenticated ciphertext (Fernet AES-128-CBC + HMAC-SHA256).
- `seen_hashes` contains only SHA256 hashes and unix epoch timestamps;
  NO plaintext titles or article content.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from src.bot.logger import get_logger

logger = get_logger(__name__)

CURRENT_SCHEMA_VERSION = 1
DEFAULT_RETENTION_SECONDS = 14 * 86400  # 14 days


@dataclass
class BotState:
    """In-memory state representation."""

    schema_version: int = CURRENT_SCHEMA_VERSION
    updated_at: float = field(default_factory=time.time)
    telegram_update_offset: int = 0
    seen_hashes: dict[str, float] = field(default_factory=dict)
    seen_simhashes: dict[str, float] = field(default_factory=dict)
    feed_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    muted_sectors: list[str] = field(default_factory=list)
    watchlist: list[str] = field(default_factory=list)
    paused: bool = False
    digest_history: dict[str, bool] = field(default_factory=dict)
    digest_queue: list[dict[str, Any]] = field(default_factory=list)
    pending_digest: bool = False
    pending_crypto: bool = False
    pending_crypto_filter: str = ""
    pending_markets: bool = False
    llm_usage: dict[str, Any] = field(
        default_factory=lambda: {
            "day": time.strftime("%Y-%m-%d"),
            "tokens_today": 0,
            "calls_today": 0,
        }
    )

    def prune_retention(self, retention_seconds: float = DEFAULT_RETENTION_SECONDS) -> None:
        """Prune hashes older than retention period."""
        cutoff = time.time() - retention_seconds
        initial_seen = len(self.seen_hashes)
        self.seen_hashes = {h: ts for h, ts in self.seen_hashes.items() if ts >= cutoff}
        self.seen_simhashes = {h: ts for h, ts in self.seen_simhashes.items() if ts >= cutoff}
        pruned = initial_seen - len(self.seen_hashes)
        if pruned > 0:
            logger.info("pruned expired items from seen store", extra={"pruned_count": pruned})
        # Prune queued digest items older than 48 hours
        queue_cutoff = time.time() - 48 * 3600
        self.digest_queue = [
            item for item in self.digest_queue if item.get("timestamp", time.time()) >= queue_cutoff
        ]
        if len(self.digest_queue) > 50:
            self.digest_queue = self.digest_queue[-50:]

    def to_json(self) -> str:
        """Serialize state to JSON string."""
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> BotState:
        """Deserialize state from JSON string with schema migration."""
        data = json.loads(raw)
        version = data.get("schema_version", 1)
        if version > CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"State schema version {version} is newer than supported {CURRENT_SCHEMA_VERSION}"
            )
        return cls(
            schema_version=CURRENT_SCHEMA_VERSION,
            updated_at=data.get("updated_at", time.time()),
            telegram_update_offset=data.get("telegram_update_offset", 0),
            seen_hashes=data.get("seen_hashes", {}),
            seen_simhashes=data.get("seen_simhashes", {}),
            feed_states=data.get("feed_states", {}),
            muted_sectors=data.get("muted_sectors", []),
            watchlist=data.get("watchlist", []),
            paused=data.get("paused", False),
            digest_history=data.get("digest_history", {}),
            digest_queue=data.get("digest_queue", []),
            pending_digest=data.get("pending_digest", False),
            pending_crypto=data.get("pending_crypto", False),
            pending_crypto_filter=data.get("pending_crypto_filter", ""),
            pending_markets=data.get("pending_markets", False),
            llm_usage=data.get(
                "llm_usage",
                {
                    "day": time.strftime("%Y-%m-%d"),
                    "tokens_today": 0,
                    "calls_today": 0,
                },
            ),
        )


class StateManager:
    """Handles loading, encrypting, decrypting, and saving bot state."""

    STATE_FILE_NAME = "state.enc"
    STATE_BRANCH = "state"

    def __init__(
        self,
        encryption_key: str,
        repo_root: Path | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        self._dry_run = dry_run
        self._repo_root = repo_root or Path(__file__).resolve().parent.parent.parent
        self._fernet: Fernet | None = None

        if encryption_key:
            try:
                # Ensure key is valid Fernet (32 urlsafe-base64 bytes)
                self._fernet = Fernet(encryption_key.encode("ascii"))
            except Exception as e:
                if self._dry_run:
                    logger.warning("invalid key in dry-run mode", extra={"error": str(e)})
                    self._fernet = None
                else:
                    raise ValueError(f"Invalid STATE_ENCRYPTION_KEY format: {e}") from e

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt plaintext string into Fernet ciphertext."""
        if not self._fernet:
            raise ValueError("Cannot encrypt: STATE_ENCRYPTION_KEY not set")
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt Fernet ciphertext into plaintext string."""
        if not self._fernet:
            raise ValueError("Cannot decrypt: STATE_ENCRYPTION_KEY not set")
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as e:
            raise ValueError("Failed to decrypt state: invalid key or corrupted ciphertext") from e

    def load_state(self) -> BotState:
        """Load and decrypt state from git branch or local storage."""
        if self._dry_run or not self._fernet:
            logger.info("loading empty state (dry-run or missing encryption key)")
            return BotState()

        # Try to read state.enc from the state branch using git show
        try:
            cmd = ["git", "show", f"{self.STATE_BRANCH}:{self.STATE_FILE_NAME}"]
            result = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                plaintext = self.decrypt(result.stdout)
                state = BotState.from_json(plaintext)
                state.prune_retention()
                logger.info(
                    "state loaded and decrypted successfully",
                    extra={"seen_count": len(state.seen_hashes)},
                )
                return state
        except Exception as e:
            logger.warning(
                "failed to load state from git branch, starting fresh",
                extra={"error": str(e)},
            )

        # Also check local file for local testing
        local_enc = self._repo_root / self.STATE_FILE_NAME
        if local_enc.is_file():
            try:
                ciphertext = local_enc.read_bytes()
                plaintext = self.decrypt(ciphertext)
                state = BotState.from_json(plaintext)
                state.prune_retention()
                logger.info("loaded state from local file")
                return state
            except Exception as e:
                logger.warning("failed to load local state file", extra={"error": str(e)})

        logger.info("initialized new state")
        return BotState()

    def save_state(self, state: BotState) -> None:
        """Encrypt and persist state to the state branch."""
        if self._dry_run:
            logger.info("skipping state save in dry-run mode")
            return

        if not self._fernet:
            logger.warning("skipping state save: no encryption key")
            return

        state.updated_at = time.time()
        state.prune_retention()
        plaintext = state.to_json()
        ciphertext = self.encrypt(plaintext)

        # In git environment, commit ciphertext to state branch
        try:
            self._commit_to_state_branch(ciphertext)
            logger.info(
                "state encrypted and committed to state branch",
                extra={"seen_count": len(state.seen_hashes)},
            )
        except Exception as e:
            logger.error("failed to commit state to git branch", extra={"error": str(e)})
            # Save locally as emergency fallback
            (self._repo_root / self.STATE_FILE_NAME).write_bytes(ciphertext)

    MAX_STATE_COMMITS: int = 50

    def squash_history(self, state: BotState) -> None:
        """Explicitly squash the state branch history into a single commit."""
        if self._dry_run or not self._fernet:
            return
        ciphertext = self.encrypt(state.to_json())
        self._commit_to_state_branch(ciphertext, force_squash=True)
        logger.info("state history successfully squashed to 1 commit")

    def _commit_to_state_branch(self, ciphertext: bytes, force_squash: bool = False) -> None:
        """Commit encrypted blob to orphan state branch using git commands."""
        # Use git hash-object and update-index to write directly without checking out the branch
        # 1. Write blob into git object database
        p_hash = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            input=ciphertext,
            cwd=str(self._repo_root),
            capture_output=True,
            check=True,
        )
        blob_sha = p_hash.stdout.decode("ascii").strip()

        # 2. Get tree for the commit
        # Check if state branch exists
        ref_check = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{self.STATE_BRANCH}"],
            cwd=str(self._repo_root),
            capture_output=True,
            check=False,
        )
        parent_sha: str | None = None
        if ref_check.returncode == 0:
            parent_sha = ref_check.stdout.decode("ascii").strip()

        # Check commit count to auto-squash
        should_squash = force_squash
        if parent_sha and not should_squash:
            count_check = subprocess.run(
                ["git", "rev-list", "--count", f"refs/heads/{self.STATE_BRANCH}"],
                cwd=str(self._repo_root),
                capture_output=True,
                check=False,
            )
            if count_check.returncode == 0:
                try:
                    num_commits = int(count_check.stdout.decode("ascii").strip())
                    if num_commits >= self.MAX_STATE_COMMITS:
                        should_squash = True
                        logger.info(
                            "state commit count exceeded threshold; squashing history",
                            extra={"commits": num_commits},
                        )
                except ValueError:
                    pass

        # Write tree with state.enc entry
        # Format: 100644 blob <sha>\tstate.enc\n
        tree_input = f"100644 blob {blob_sha}\t{self.STATE_FILE_NAME}\n"
        p_tree = subprocess.run(
            ["git", "mktree"],
            input=tree_input.encode("ascii"),
            cwd=str(self._repo_root),
            capture_output=True,
            check=True,
        )
        tree_sha = p_tree.stdout.decode("ascii").strip()

        bot_email = "41898282+github-actions[bot]@users.noreply.github.com"
        git_env = os.environ.copy()
        git_env.setdefault("GIT_AUTHOR_NAME", "github-actions[bot]")
        git_env.setdefault("GIT_AUTHOR_EMAIL", bot_email)
        git_env.setdefault("GIT_COMMITTER_NAME", "github-actions[bot]")
        git_env.setdefault("GIT_COMMITTER_EMAIL", bot_email)

        commit_msg = "state: squashed history" if should_squash else "update state"
        commit_cmd = ["git", "commit-tree", tree_sha, "-m", commit_msg]
        if parent_sha and not should_squash:
            commit_cmd.extend(["-p", parent_sha])
        p_commit = subprocess.run(
            commit_cmd,
            cwd=str(self._repo_root),
            capture_output=True,
            check=True,
            env=git_env,
        )
        commit_sha = p_commit.stdout.decode("ascii").strip()

        # 4. Update state branch ref
        subprocess.run(
            ["git", "update-ref", f"refs/heads/{self.STATE_BRANCH}", commit_sha],
            cwd=str(self._repo_root),
            check=True,
        )
