"""Install the Windows scheduled task for outbound follow-ups."""

from __future__ import annotations

import sys

from followup_automation import TASK_NAME, ensure_automatic_followups, install_windows_task


def main() -> int:
    if install_windows_task() != 0:
        return 1
    print(
        f"Installed {TASK_NAME} (local fallback — PC must be on). "
        "For PC-off follow-ups: python cloud/deploy.py --host user@your-server"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
