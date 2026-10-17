#!/usr/bin/env python3
"""Generate a random encryption key for STATE_ENCRYPTION_KEY.

Usage:
    python scripts/generate_state_key.py

Copy the output and set it as the STATE_ENCRYPTION_KEY secret in your
GitHub repository's 'production' environment.
"""

import base64
import secrets


def main() -> None:
    # 32 bytes = 256-bit key for AES-256 or Fernet
    key = secrets.token_bytes(32)
    encoded = base64.urlsafe_b64encode(key).decode("ascii")
    print("Generated STATE_ENCRYPTION_KEY (base64url, 256-bit):")
    print()
    print(f"  {encoded}")
    print()
    print('Set this as a GitHub Environment secret in the "production" environment.')
    print("Keep a backup in a password manager. If lost, state cannot be decrypted.")


if __name__ == "__main__":
    main()
