"""Preview generated outbound sequences without scheduling or sending."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from mistral_client import generate_email_sequence
from part2_outbound import _dedupe_targets


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Outbound JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview Mistral-generated outbound emails without sending."
    )
    parser.add_argument("source", help="Path to outbound JSON")
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Maximum recipients to preview (default: 3)",
    )
    args = parser.parse_args()

    payload = _load_payload(Path(args.source))
    company = str(payload["company"])
    targets = _dedupe_targets(payload.get("outbound_targets", []))[: args.limit]

    if not targets:
        print("No outbound targets with emails found.", file=sys.stderr)
        return 1

    print(f"Previewing {len(targets)} sequence(s) for {company}. No emails will be sent.")
    for target in targets:
        name = str(target.get("name") or "")
        title = str(target.get("title") or "")
        email = str(target.get("email") or "")
        role_priority = str(target.get("role_priority") or "recruiter")

        print("\n" + "=" * 80)
        print(f"Recipient: {name} <{email}>")
        print(f"Title: {title or role_priority}")

        sequence = generate_email_sequence(
            company=company,
            recipient_name=name,
            recipient_title=title,
            role_priority=role_priority,
        )
        for message in sequence:
            print("\n" + "-" * 80)
            print(f"Step {message['step']}: {message['subject']}")
            print(message["body"])

    print("\nPreview complete. No scheduling or sending happened.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
