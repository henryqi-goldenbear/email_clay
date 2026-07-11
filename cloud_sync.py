"""Push/pull follow-up state to a cloud runner (GitHub Actions or VPS)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from github_sync import is_github_cloud_configured, pull_github_state, push_github_state
from paths import (
    CONTACTS_DB,
    PROJECT_DIR,
    GMAIL_TOKENS,
    RESUME_PDF,
    SCHEDULER_LOG,
)

CLOUD_DIR = PROJECT_DIR / "cloud"
CONFIG_PATH = CLOUD_DIR / "config.json"

SYNC_FILES = (
    CONTACTS_DB,
    RESUME_PDF,
    SCHEDULER_LOG,
)


def _load_env() -> None:
    load_dotenv(PROJECT_DIR / ".env")


def is_ssh_cloud_configured() -> bool:
    _load_env()
    return bool(os.getenv("CLOUD_SSH_HOST", "").strip())


def is_cloud_configured() -> bool:
    return is_github_cloud_configured() or is_ssh_cloud_configured()


def _ssh_host() -> str:
    _load_env()
    host = os.getenv("CLOUD_SSH_HOST", "").strip()
    if not host:
        raise RuntimeError(
            "CLOUD_SSH_HOST is not set in .env. "
            "Use free GitHub Actions instead: python cloud/deploy_github.py"
        )
    return host


def _remote_dir() -> str:
    if CONFIG_PATH.exists():
        configured = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("remote_dir")
        if configured:
            return str(configured)
    _load_env()
    return os.getenv("CLOUD_REMOTE_DIR", "~/clay_outbound/data").strip()


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}\n{result.stderr}"
        )


def _scp(local: Path, remote_path: str, *, to_remote: bool) -> None:
    host = _ssh_host()
    if to_remote:
        _run(["scp", str(local), f"{host}:{remote_path}"])
    else:
        _run(["scp", f"{host}:{remote_path}", str(local)])


def _push_ssh(*, quiet: bool = False) -> None:
    host = _ssh_host()
    remote = _remote_dir()
    _run(["ssh", host, f"mkdir -p {remote}"])

    for source in SYNC_FILES:
        if not source.exists():
            if source.name == SCHEDULER_LOG.name:
                continue
            raise FileNotFoundError(f"Required file not found: {source}")
        remote_file = f"{remote}/{source.name}"
        _scp(source, remote_file, to_remote=True)
        if not quiet:
            print(f"  uploaded {source.name} -> {host}:{remote_file}")

    env_source = PROJECT_DIR / ".env"
    if env_source.exists():
        _scp(env_source, f"{remote}/.env", to_remote=True)
        if not quiet:
            print(f"  uploaded .env -> {host}:{remote}/.env")

    if not quiet:
        print(f"Cloud state synced to {host}:{remote}")


def _pull_ssh(*, quiet: bool = False) -> None:
    remote = _remote_dir()
    for filename in (CONTACTS_DB.name, GMAIL_TOKENS.name, SCHEDULER_LOG.name):
        destination = PROJECT_DIR / filename
        try:
            _scp(destination, f"{remote}/{filename}", to_remote=False)
            if not quiet:
                print(f"  downloaded {filename}")
        except RuntimeError as exc:
            if "No such file" in str(exc) or "not found" in str(exc).lower():
                if not quiet:
                    print(f"  skip missing {filename}")
                continue
            raise
    if not quiet:
        print("Cloud state pulled to local project folder.")


def push_followup_state(*, quiet: bool = False) -> None:
    if is_github_cloud_configured():
        push_github_state(quiet=quiet)
        return
    if is_ssh_cloud_configured():
        _push_ssh(quiet=quiet)
        return
    raise RuntimeError(
        "No cloud follow-ups configured. Run: python cloud/deploy_github.py"
    )


def pull_followup_state(*, quiet: bool = False) -> None:
    if is_github_cloud_configured():
        pull_github_state(quiet=quiet)
        return
    if is_ssh_cloud_configured():
        _pull_ssh(quiet=quiet)
        return
    raise RuntimeError("No cloud follow-ups configured.")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Sync follow-up state with cloud runner.")
    parser.add_argument("direction", choices=["push", "pull"])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        if args.direction == "push":
            push_followup_state(quiet=args.quiet)
        else:
            pull_followup_state(quiet=args.quiet)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
