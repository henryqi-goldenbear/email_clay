"""Part 2: Schedule and send outbound recruiting email sequences."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import (
    create_or_get_campaign,
    get_contacts_for_company,
    get_due_messages,
    mark_company_step1_due,
    mark_message_failed,
    mark_message_sent,
    schedule_campaign_messages,
)
from email_sender import EmailSendError, send_email
from scheduler import is_send_window_open, next_business_slot, schedule_followup, to_business_timezone

OUTBOUND_DIR = Path(__file__).parent / "outbound_queue"

FOLLOWUP_DAY_1 = 1
FOLLOWUP_DAY_3 = 3
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _dedupe_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for target in targets:
        email = (target.get("email") or "").strip().lower()
        if not EMAIL_PATTERN.fullmatch(email) or email in seen:
            continue
        seen.add(email)
        unique.append(target)
    return unique


def load_outbound_payload(source: str | Path) -> dict[str, Any]:
    path = Path(source)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    contacts = get_contacts_for_company(str(source))
    recruiters = [
        {
            "name": c["name"],
            "title": c["title"],
            "email": c["email"],
            "role_priority": c["role_priority"],
            "linkedin_url": c["linkedin_url"],
        }
        for c in contacts
        if c.get("email")
    ]
    return {
        "company": str(source),
        "company_identifier": contacts[0]["company_identifier"] if contacts else None,
        "outbound_targets": recruiters,
    }


def build_outbound_payload(company_name: str) -> dict[str, Any]:
    contacts = get_contacts_for_company(company_name)
    seen_emails: set[str] = set()
    recruiters: list[dict[str, Any]] = []
    for contact in reversed(contacts):
        email = (contact.get("email") or "").strip().lower()
        if not EMAIL_PATTERN.fullmatch(email) or email in seen_emails:
            continue
        seen_emails.add(email)
        recruiters.append(
            {
                "name": contact["name"],
                "title": contact["title"],
                "email": contact["email"],
                "role_priority": contact["role_priority"],
                "linkedin_url": contact["linkedin_url"],
            }
        )
    recruiters.reverse()

    identifier = next(
        (c["company_identifier"] for c in contacts if c.get("company_identifier")),
        None,
    )

    return {
        "company": company_name,
        "company_identifier": identifier,
        "total_contacts": len(contacts),
        "recruiters_with_email": len(recruiters),
        "contacts": contacts,
        "outbound_targets": recruiters,
    }


def send_to_part2(company_name: str) -> Path:
    """Queue company + recruiter emails for outbound processing."""
    payload = build_outbound_payload(company_name)
    OUTBOUND_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(ch if ch.isalnum() else "_" for ch in company_name.lower())
    output_path = OUTBOUND_DIR / f"{safe_name}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def schedule_campaign_for_contact(
    *,
    company: str,
    contact: dict[str, Any],
) -> dict[str, Any]:
    from mistral_client import generate_email_sequence

    emails = generate_email_sequence(
        company=company,
        recipient_name=str(contact.get("name") or ""),
        recipient_title=str(contact.get("title") or ""),
        role_priority=str(contact.get("role_priority") or "recruiter"),
    )

    first_slot = next_business_slot()
    schedule_map = {
        1: first_slot,
        2: schedule_followup(first_slot, FOLLOWUP_DAY_1),
        3: schedule_followup(first_slot, FOLLOWUP_DAY_3),
    }

    campaign_id = create_or_get_campaign(
        company=company,
        contact_email=str(contact["email"]),
        contact_name=str(contact.get("name") or ""),
        contact_title=str(contact.get("title") or ""),
        role_priority=str(contact.get("role_priority") or "recruiter"),
    )

    scheduled_messages = []
    for email in emails:
        step = int(email["step"])
        scheduled_messages.append(
            {
                "step": str(step),
                "subject": email["subject"],
                "body": email["body"],
                "scheduled_at": _iso(schedule_map[step]),
            }
        )

    schedule_campaign_messages(campaign_id, scheduled_messages)

    return {
        "campaign_id": campaign_id,
        "contact_email": contact["email"],
        "contact_name": contact.get("name"),
        "scheduled_messages": [
            {
                "step": int(m["step"]),
                "subject": m["subject"],
                "scheduled_at": m["scheduled_at"],
            }
            for m in scheduled_messages
        ],
    }


def schedule_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    company = str(payload["company"])
    targets = _dedupe_targets(payload.get("outbound_targets", []))
    if not targets:
        raise ValueError(f"No recruiter emails found for {company}")

    results: list[dict[str, Any]] = []
    for contact in targets:
        results.append(schedule_campaign_for_contact(company=company, contact=contact))
    return results


def schedule_from_json(source: str | Path) -> list[dict[str, Any]]:
    payload = load_outbound_payload(source)
    return schedule_from_payload(payload)


def run_due_sends(
    *,
    dry_run: bool = False,
    force: bool = False,
    company: str | None = None,
) -> list[dict[str, Any]]:
    if not force and not dry_run and not is_send_window_open():
        now = to_business_timezone()
        return [
            {
                "status": "skipped",
                "reason": (
                    f"Outside business hours ({now.strftime('%A %I:%M %Z')}). "
                    "Use --force to override."
                ),
            }
        ]

    due = get_due_messages(company=company)
    results: list[dict[str, Any]] = []

    for message in due:
        step = int(message["step"])
        try:
            send_email(
                to_email=message["contact_email"],
                subject=message["subject"],
                body=message["body"],
                attach_resume=(step == 1),
                dry_run=dry_run,
            )
            if not dry_run:
                mark_message_sent(int(message["message_id"]))
            results.append(
                {
                    "status": "sent" if not dry_run else "dry_run",
                    "message_id": message["message_id"],
                    "step": step,
                    "to": message["contact_email"],
                    "company": message["company"],
                }
            )
        except EmailSendError as exc:
            if not dry_run:
                mark_message_failed(int(message["message_id"]), str(exc))
            results.append(
                {
                    "status": "failed",
                    "message_id": message["message_id"],
                    "step": step,
                    "to": message["contact_email"],
                    "error": str(exc),
                }
            )

    return results


def run_full_outbound(
    company: str,
    *,
    dry_run: bool = False,
    send_now: bool = True,
) -> dict[str, Any]:
    """Queue, schedule sequences, and send step-1 emails via Gmail."""
    outbound_path = send_to_part2(company)
    payload = load_outbound_payload(outbound_path)
    targets = _dedupe_targets(payload.get("outbound_targets", []))
    if not targets:
        raise ValueError(f"No recruiter emails found for {company}")

    print(f"Generating email sequences for {len(targets)} recruiter(s)...")
    scheduled = schedule_from_payload(payload)

    sent: list[dict[str, Any]] = []
    if send_now:
        due_count = mark_company_step1_due(company)
        print(f"Sending step 1 to {due_count} recruiter(s) via Gmail...")
        sent = run_due_sends(dry_run=dry_run, force=True, company=company)

    return {
        "company": company,
        "outbound_path": str(outbound_path),
        "scheduled": scheduled,
        "sent": sent,
    }
