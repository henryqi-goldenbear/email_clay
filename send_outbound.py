"""CLI for scheduling and sending outbound recruiting emails."""

from __future__ import annotations

import argparse
import json
import sys

from db import mark_campaign_replied
from part2_outbound import run_due_sends, schedule_from_json, send_to_part2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Schedule and send outbound recruiting email sequences."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    queue_parser = subparsers.add_parser("queue", help="Build outbound JSON from DB")
    queue_parser.add_argument("company", help="Company name")

    schedule_parser = subparsers.add_parser(
        "schedule",
        help="Generate Mistral copy and schedule sequence from outbound JSON",
    )
    schedule_parser.add_argument(
        "source",
        help="Path to outbound JSON or company name",
    )

    run_parser = subparsers.add_parser("run", help="Send due scheduled emails")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print emails without sending",
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="Send even outside business hours",
    )
    run_parser.add_argument(
        "--company",
        help="Only send due messages for this company",
    )

    mark_parser = subparsers.add_parser(
        "mark-replied",
        help="Stop follow-ups for a campaign after a recruiter replies",
    )
    mark_parser.add_argument("email", help="Recruiter email address")
    mark_parser.add_argument("--company", required=True, help="Company name")

    args = parser.parse_args()

    if args.command == "queue":
        path = send_to_part2(args.company)
        print(f"Queued outbound payload: {path}")
        return 0

    if args.command == "schedule":
        print(f"Scheduling outbound sequence from {args.source}...")
        results = schedule_from_json(args.source)
        print(json.dumps(results, indent=2))
        print(f"Scheduled {len(results)} recruiter sequences.")
        return 0

    if args.command == "run":
        results = run_due_sends(
            dry_run=args.dry_run,
            force=args.force,
            company=args.company,
        )
        print(json.dumps(results, indent=2))
        if any(r.get("status") == "failed" for r in results):
            return 1
        return 0

    if args.command == "mark-replied":
        import sqlite3
        from db import DEFAULT_DB_PATH, init_db

        init_db()
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            row = conn.execute(
                """
                SELECT id FROM outbound_campaigns
                WHERE company = ? AND contact_email = ?
                """,
                (args.company, args.email),
            ).fetchone()
        if not row:
            print("Campaign not found.", file=sys.stderr)
            return 1
        mark_campaign_replied(int(row[0]))
        print(f"Marked {args.email} at {args.company} as replied; follow-ups skipped.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
