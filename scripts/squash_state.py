#!/usr/bin/env python3
"""Squash the git history of the orphan `state` branch to a single commit.

Usage:
    python scripts/squash_state.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to sys.path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from src.bot.logger import get_logger, setup_logging
from src.state.manager import StateManager

setup_logging()
logger = get_logger("squash_state")


def main() -> int:
    key = os.environ.get("STATE_ENCRYPTION_KEY", "")
    if not key:
        print("ERROR: STATE_ENCRYPTION_KEY environment variable is not set.", file=sys.stderr)
        return 1

    manager = StateManager(encryption_key=key, repo_root=root)
    state = manager.load_state()
    manager.squash_history(state)
    print("State history squashed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
