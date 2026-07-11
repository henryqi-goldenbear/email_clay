"""One-time deploy of the always-on cloud follow-up worker."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
CLOUD_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CLOUD_DIR / "config.json"
REMOTE_APP_DIR = "~/clay_outbound"
REMOTE_DATA_DIR = f"{REMOTE_APP_DIR}/data"


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}"
        )
    return result


def _update_local_env(host: str) -> None:
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

    set_key("CLOUD_SSH_HOST", host)
    set_key("CLOUD_REMOTE_DIR", REMOTE_DATA_DIR)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def deploy(host: str) -> None:
    print(f"Deploying cloud worker to {host}...")

    _run(["ssh", host, f"mkdir -p {REMOTE_APP_DIR}/data {REMOTE_APP_DIR}/cloud"])

    files_to_copy = [
        (CLOUD_DIR / "docker-compose.yml", f"{REMOTE_APP_DIR}/docker-compose.yml"),
        (CLOUD_DIR / "Dockerfile", f"{REMOTE_APP_DIR}/cloud/Dockerfile"),
        (CLOUD_DIR / "entrypoint.sh", f"{REMOTE_APP_DIR}/cloud/entrypoint.sh"),
        (CLOUD_DIR / "crontab", f"{REMOTE_APP_DIR}/cloud/crontab"),
        (CLOUD_DIR / "requirements.txt", f"{REMOTE_APP_DIR}/cloud/requirements.txt"),
    ]
    app_files = [
        "paths.py",
        "db.py",
        "part2_outbound.py",
        "email_sender.py",
        "scheduler.py",
        "resume.py",
        "gmail_oauth.py",
        "run_scheduled_outbound.py",
    ]
    for name in app_files:
        files_to_copy.append((PROJECT_DIR / name, f"{REMOTE_APP_DIR}/{name}"))

    for local_path, remote_path in files_to_copy:
        _run(["scp", str(local_path), f"{host}:{remote_path}"])
        print(f"  copied {local_path.name}")

    remote_compose = CLOUD_DIR / "docker-compose.remote.yml"
    remote_compose.write_text(
        """services:
  followups:
    build:
      context: .
      dockerfile: cloud/Dockerfile
    restart: unless-stopped
    volumes:
      - ./data:/data
""",
        encoding="utf-8",
    )
    _run(["scp", str(remote_compose), f"{host}:{REMOTE_APP_DIR}/docker-compose.yml"])
    remote_compose.unlink(missing_ok=True)

    print("Building and starting Docker container on server...")
    result = _run(
        ["ssh", host, f"cd {REMOTE_APP_DIR} && docker compose up -d --build"],
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(
            "Docker deploy failed. Ensure Docker is installed on the server. "
            "Try: ssh into server and run `docker compose version`"
        )

    _update_local_env(host)
    CONFIG_PATH.write_text(
        json.dumps(
            {
                "host": host,
                "remote_dir": REMOTE_DATA_DIR,
                "remote_app_dir": REMOTE_APP_DIR,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nCloud worker deployed.")
    print("Next: python cloud_sync.py push")
    print("Then run campaigns locally with: python main.py <company>")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deploy always-on follow-up worker to a VPS (not AWS)."
    )
    parser.add_argument(
        "--host",
        required=True,
        help="SSH target, e.g. root@123.45.67.89",
    )
    args = parser.parse_args()

    try:
        deploy(args.host.strip())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
