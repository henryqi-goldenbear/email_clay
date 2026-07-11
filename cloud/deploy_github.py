"""Set up free GitHub Actions follow-ups (no server cost)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "github_config.json"

SECRET_KEYS = (
    "GMAIL_OAUTH_CLIENT_ID",
    "GMAIL_OAUTH_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "SENDER_EMAIL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "BUSINESS_TIMEZONE",
    "BUSINESS_HOUR_START",
    "BUSINESS_HOUR_END",
)


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _run(command: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=cwd or PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def _update_local_env() -> None:
    env_path = PROJECT_DIR / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    def set_key(key: str, value: str) -> None:
        nonlocal lines
        prefix = f"{key}="
        replaced = False
        for index, line in enumerate(lines):
            if line.startswith(prefix):
                lines[index] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")

    set_key("CLOUD_FOLLOWUPS", "github")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_secrets_checklist(env_values: dict[str, str]) -> None:
    print("\nAdd these GitHub repository secrets (Settings -> Secrets -> Actions):\n")
    defaults = {
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "BUSINESS_TIMEZONE": "America/Los_Angeles",
        "BUSINESS_HOUR_START": "8",
        "BUSINESS_HOUR_END": "17",
    }
    for key in SECRET_KEYS:
        if key == "GMAIL_REFRESH_TOKEN":
            token_path = PROJECT_DIR / ".gmail_tokens.json"
            if token_path.exists():
                payload = json.loads(token_path.read_text(encoding="utf-8"))
                value = str(payload.get("refresh_token") or "")
                status = "copy value below into GitHub secret" if value else "MISSING"
                print(f"  {key} = ({status})")
            else:
                print(f"  {key} = MISSING (.gmail_tokens.json not found)")
            continue
        value = env_values.get(key) or defaults.get(key, "")
        status = "ok" if value else "MISSING in .env"
        print(f"  {key} = {value or status}")
    print("\nRepo must be PRIVATE.")
    print("Gmail tokens go in Secrets only (never in git).")
    print("Enable Actions: Settings -> Actions -> General -> Allow all actions.")


def deploy() -> None:
    if not (PROJECT_DIR / ".git").exists():
        _run(["git", "init"])
        print("Initialized git repository in clay_outbound.")

    _update_local_env()
    env_values = _load_env_file(PROJECT_DIR / ".env")
    _print_secrets_checklist(env_values)

    remote = ""
    try:
        remote = _run(["git", "remote", "get-url", "origin"])
    except RuntimeError:
        print(
            "\nCreate a PRIVATE GitHub repo, then run:\n"
            "  git remote add origin https://github.com/henryqi-goldenbear/email_clay.git\n"
            "  git add .\n"
            "  git commit -m \"Initial commit\"\n"
            "  git push -u origin main\n"
        )

    if remote:
        CONFIG_PATH.write_text(
            json.dumps({"mode": "github", "remote": remote}, indent=2),
            encoding="utf-8",
        )

    workflow = PROJECT_DIR / ".github" / "workflows" / "clay-outbound-followups.yml"
    if not workflow.exists():
        raise RuntimeError(f"Missing workflow file: {workflow}")

    print("\nGitHub Actions follow-ups configured locally.")
    print("Next steps:")
    print("  1. Push this repo to GitHub (private)")
    print("  2. Add the secrets listed above")
    print("  3. python github_sync.py push")
    print("  4. python main.py <company>  # auto-syncs after each campaign")
    print("\nCost: $0 on GitHub free plan (~1500 min/month used for private repos).")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enable free GitHub Actions follow-ups (PC can be off)."
    )
    args = parser.parse_args()
    try:
        deploy()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
