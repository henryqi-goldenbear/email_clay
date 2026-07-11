"""Print the Gmail refresh token for GitHub Secrets setup."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOKEN_PATH = Path(__file__).resolve().parent.parent / ".gmail_tokens.json"


def main() -> int:
    if not TOKEN_PATH.exists():
        print("Run first: python gmail_oauth.py", file=sys.stderr)
        return 1

    payload = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    refresh = payload.get("refresh_token")
    if not refresh:
        print("No refresh_token in .gmail_tokens.json. Re-run: python gmail_oauth.py", file=sys.stderr)
        return 1

    print("Add this GitHub repository secret:")
    print("  Name:  GMAIL_REFRESH_TOKEN")
    print(f"  Value: {refresh}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
