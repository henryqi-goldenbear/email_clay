"""End-to-end simulation of the outbound email sequence (dry-run only)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from db import DEFAULT_DB_PATH, init_db, mark_message_sent
from part2_outbound import run_due_sends, schedule_from_json

SIM_JSON = Path(__file__).parent / "outbound_queue" / "nebula_systems.json"


def _set_step_due(campaign_id: int, step: int) -> None:
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute(
            """
            UPDATE outbound_messages
            SET scheduled_at = '2020-01-01T00:00:00+00:00'
            WHERE campaign_id = ? AND step = ?
            """,
            (campaign_id, step),
        )
        conn.commit()


def _print_due_messages() -> None:
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT c.company, c.contact_name, c.contact_email,
                   m.step, m.subject, m.status, m.scheduled_at
            FROM outbound_messages m
            JOIN outbound_campaigns c ON c.id = m.campaign_id
            WHERE c.company = 'Nebula Systems'
            ORDER BY c.contact_email, m.step
            """
        ).fetchall()
    print("\n--- Scheduled sequence ---")
    for row in rows:
        print(
            f"  {row['contact_name']} <{row['contact_email']}> "
            f"| step {row['step']} | {row['status']} | {row['subject'][:50]}"
        )


def main() -> int:
    init_db()

    print("=== Simulating outbound sequence for Nebula Systems ===\n")
    print("1) Generating Mistral copy + scheduling (fake company, fake emails)...")
    scheduled = schedule_from_json(SIM_JSON)
    print(json.dumps(scheduled, indent=2))

    _print_due_messages()

    for step in (1, 2, 3):
        print(f"\n2.{step}) Dry-run send for step {step}...")
        campaign_ids = {item["campaign_id"] for item in scheduled}
        for campaign_id in campaign_ids:
            _set_step_due(campaign_id, step)

        results = run_due_sends(dry_run=True, force=True)
        print(json.dumps(results, indent=2))

        if not results:
            print(f"  (no step {step} messages due — prior step may not be marked sent)")
            continue

        if step < 3:
            with sqlite3.connect(DEFAULT_DB_PATH) as conn:
                for row in results:
                    if row.get("status") == "dry_run":
                        mark_message_sent(int(row["message_id"]))
            print(f"  Marked step {step} as sent so step {step + 1} can fire next.")

    print("\n=== Simulation complete (no real emails sent) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
