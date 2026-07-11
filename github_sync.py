"""Push/pull follow-up state via a private GitHub repo (free GitHub Actions)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from paths import (
    CONTACTS_DB,
    GMAIL_TOKENS,
    PROJECT_DIR,
    RESUME_PDF,
    SCHEDULER_LOG,
)

CLOUD_STATE_BRANCH = "cloud-state"

SYNC_FILES = (
    CONTACTS_DB,
    GMAIL_TOKENS,
    RESUME_PDF,
    SCHEDULER_LOG,
)


def _load_env() -> None:
    load_dotenv(PROJECT_DIR / ".env")


def is_github_cloud_configured() -> bool:
    _load_env()
    return os.getenv("CLOUD_FOLLOWUPS", "").strip().lower() == "github"


def _run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd or PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def _git_repo_ready() -> bool:
    if not (PROJECT_DIR / ".git").exists():
        return False
    try:
        _run(["git", "remote", "get-url", "origin"])
        return True
    except RuntimeError:
        return False


def push_github_state(*, quiet: bool = False) -> None:
    """Upload local DB, tokens, and resume to the cloud-state branch."""
    if not _git_repo_ready():
        raise RuntimeError(
            "Git remote not configured. Run: python cloud/deploy_github.py"
        )

    for source in SYNC_FILES:
        if not source.exists() and source.name != SCHEDULER_LOG.name:
            raise FileNotFoundError(f"Required file not found: {source}")

    remote = _run(["git", "remote", "get-url", "origin"])

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        _run(["git", "init"], cwd=work)
        _run(["git", "remote", "add", "origin", remote], cwd=work)

        for source in SYNC_FILES:
            if source.exists():
                shutil.copy2(source, work / source.name)

        _run(["git", "checkout", "--orphan", CLOUD_STATE_BRANCH], cwd=work)
        _run(["git", "add", "-A"], cwd=work)

        if subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=work,
            capture_output=True,
        ).returncode != 0:
            _run(
                [
                    "git",
                    "-c",
                    "user.name=Clay Outbound",
                    "-c",
                    "user.email=clay-outbound@local",
                    "commit",
                    "-m",
                    "sync outbound state",
                ],
                cwd=work,
            )

        _run(["git", "push", "--force", "origin", f"HEAD:{CLOUD_STATE_BRANCH}"], cwd=work)

    if not quiet:
        print(f"Pushed follow-up state to origin/{CLOUD_STATE_BRANCH}")


def pull_github_state(*, quiet: bool = False) -> None:
    """Download updated DB, tokens, and logs from the cloud-state branch."""
    if not _git_repo_ready():
        raise RuntimeError("Git remote not configured.")

    _run(["git", "fetch", "origin", CLOUD_STATE_BRANCH])

    for source in SYNC_FILES:
        result = subprocess.run(
            ["git", "show", f"origin/{CLOUD_STATE_BRANCH}:{source.name}"],
            cwd=PROJECT_DIR,
            capture_output=True,
        )
        if result.returncode != 0:
            if source.name == SCHEDULER_LOG.name:
                if not quiet:
                    print(f"  skip missing {source.name}")
                continue
            raise RuntimeError(f"Missing {source.name} on origin/{CLOUD_STATE_BRANCH}")
        source.write_bytes(result.stdout)
        if not quiet:
            print(f"  downloaded {source.name}")

    if not quiet:
        print("GitHub cloud state pulled to local project folder.")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Sync follow-up state with free GitHub Actions cloud runner."
    )
    parser.add_argument("direction", choices=["push", "pull"])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        if args.direction == "push":
            push_github_state(quiet=args.quiet)
        else:
            pull_github_state(quiet=args.quiet)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
