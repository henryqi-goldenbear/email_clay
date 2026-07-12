"""Print values to copy into GitHub Actions secrets."""

from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_DIR / ".env"
TOKEN_PATH = PROJECT_DIR / ".gmail_tokens.json"
SECRETS_URL = "https://github.com/henryqi-goldenbear/email_clay/settings/secrets/actions"

REQUIRED = (
    "GMAIL_OAUTH_CLIENT_ID",
    "GMAIL_OAUTH_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "SENDER_EMAIL",
)

OPTIONAL = (
    ("SMTP_HOST", "smtp.gmail.com"),
    ("SMTP_PORT", "587"),
    ("SMTP_USER", "same as SENDER_EMAIL"),
    ("BUSINESS_TIMEZONE", "America/Los_Angeles"),
    ("BUSINESS_HOUR_START", "8"),
    ("BUSINESS_HOUR_END", "17"),
)


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def main() -> int:
    env = _load_env()
    refresh = ""
    if TOKEN_PATH.exists():
        refresh = str(json.loads(TOKEN_PATH.read_text(encoding="utf-8")).get("refresh_token") or "")

    print("GitHub Actions is failing because these repository secrets are missing.\n")
    print(f"Open: {SECRETS_URL}\n")
    print("Click 'New repository secret' for each REQUIRED secret:\n")

    missing = False
    for key in REQUIRED:
        if key == "GMAIL_REFRESH_TOKEN":
            value = refresh
        else:
            value = env.get(key, "")
        status = "OK - copy this value" if value else "MISSING"
        print(f"  {key}")
        print(f"    Status: {status}")
        if value:
            print(f"    Value:  {value}")
        else:
            missing = True
            if key == "GMAIL_REFRESH_TOKEN":
                print("    Fix:    python gmail_oauth.py")
            else:
                print(f"    Fix:    add {key} to .env")
        print()

    print("Optional secrets (workflow has defaults if omitted):\n")
    for key, default in OPTIONAL:
        value = env.get(key, default)
        print(f"  {key} = {value}")

    if missing:
        print("\nAdd the missing REQUIRED secrets, then re-run the workflow.")
        return 1

    print("\nAll required values found locally. Copy them into GitHub Secrets, then re-run.")
    try:
        webbrowser.open(SECRETS_URL)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
