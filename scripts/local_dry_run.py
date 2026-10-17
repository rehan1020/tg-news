#!/usr/bin/env python3
"""Run the bot locally in dry-run mode.

Usage:
    # With .env file:
    python scripts/local_dry_run.py

    # Or set env vars manually first
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    env_file = root / ".env"

    if env_file.exists():
        print(f"Loading environment from {env_file}")
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and value:
                        os.environ.setdefault(key, value)

    result = subprocess.run(
        [sys.executable, "-m", "src.bot", "--dry-run"],
        cwd=str(root),
        check=False,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
