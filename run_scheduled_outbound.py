"""Task Scheduler entrypoint for sending due outbound messages."""

from __future__ import annotations

import json
import sys
from datetime import datetime

from part2_outbound import run_due_sends
from paths import SCHEDULER_LOG
from scheduler import to_business_timezone

LOG_PATH = SCHEDULER_LOG


def _log(message: str) -> None:
    timestamp = datetime.now().astimezone().isoformat()
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")


def main() -> int:
    local_now = to_business_timezone()
    try:
        results = run_due_sends()
    except Exception as exc:
        _log(f"ERROR {type(exc).__name__}: {exc}")
        return 1

    summary = {
        "checked_at": local_now.isoformat(),
        "results": results,
    }
    _log(json.dumps(summary, ensure_ascii=True))

    if any(result.get("status") == "failed" for result in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
