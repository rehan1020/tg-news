"""Tests for state history squashing."""

from __future__ import annotations

import base64
import secrets
import subprocess

from src.state.manager import BotState, StateManager


def test_squash_state_history(tmp_path):
    """Squash history resets commit history to a single commit on state branch."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Initialize a test git repo
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test Runner"],
        cwd=str(repo),
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(repo),
        check=True,
    )

    # Initial commit on main so HEAD exists
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True)

    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    manager = StateManager(encryption_key=key, repo_root=repo)

    import time

    # Make 3 commits to state branch
    state = BotState()
    for i in range(3):
        state.seen_hashes[f"hash_{i}"] = time.time()
        manager.save_state(state)

    # Verify 3 commits exist on state branch
    p_count = subprocess.run(
        ["git", "rev-list", "--count", "refs/heads/state"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    assert int(p_count.stdout.decode("ascii").strip()) == 3

    # Now squash state history
    manager.squash_history(state)

    # Verify only 1 commit exists on state branch after squash
    p_count_squashed = subprocess.run(
        ["git", "rev-list", "--count", "refs/heads/state"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    assert int(p_count_squashed.stdout.decode("ascii").strip()) == 1

    # Verify state can still be loaded and decrypted
    loaded_state = manager.load_state()
    assert len(loaded_state.seen_hashes) == 3
