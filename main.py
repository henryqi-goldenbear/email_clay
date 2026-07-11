"""CLI entrypoint: search contacts -> schedule -> send via Gmail."""

from __future__ import annotations

import argparse
import json
import sys

from clay_auth import ClayAuthError
from cloud_sync import is_cloud_configured
from followup_automation import ensure_automatic_followups
from part1_find_contacts import run_part1
from part2_outbound import run_full_outbound


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end outbound: find recruiters via Clay, "
            "generate emails with Mistral, and send via Gmail."
        )
    )
    parser.add_argument(
        "company",
        nargs="?",
        help="Company name, e.g. OpenAI (prompted if omitted)",
    )
    parser.add_argument(
        "--identifier",
        help="Company domain or LinkedIn URL (default: <company>.com)",
    )
    parser.add_argument(
        "--max-contacts",
        type=int,
        default=4,
        help="Maximum contacts to find (default: 4)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use demo contacts (skips Clay API; useful for pipeline testing)",
    )
    parser.add_argument(
        "--find-only",
        action="store_true",
        help="Only run Clay search + save to DB, skip email scheduling/sending",
    )
    parser.add_argument(
        "--schedule-only",
        action="store_true",
        help="Schedule follow-up sequences but do not send step 1 now",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and preview step 1 without actually sending email",
    )
    args = parser.parse_args()

    company = (args.company or "").strip()
    if not company:
        company = input("Enter the company to find recruiters at: ").strip()
    if not company:
        print("Company name is required.", file=sys.stderr)
        return 1

    print(f"Step 1/3: Finding up to {args.max_contacts} contacts at {company}...")
    try:
        part1_result = run_part1(
            company_name=company,
            company_identifier=args.identifier,
            max_contacts=args.max_contacts,
            demo=args.demo,
        )
    except ClayAuthError as exc:
        print(f"Clay auth required: {exc}", file=sys.stderr)
        print("Run once: python clay_auth.py", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Clay lookup failed: {exc}", file=sys.stderr)
        if not args.demo:
            print(
                "Tip: run `python clay_auth.py` first, or use --demo to test.",
                file=sys.stderr,
            )
        return 1

    print(json.dumps(part1_result, indent=2))

    with_email = [c for c in part1_result.get("contacts", []) if c.get("email")]
    if not with_email:
        print("\nNo recruiter emails found. Cannot schedule or send.", file=sys.stderr)
        return 1

    if args.find_only:
        return 0

    print(f"\nStep 2/3: Generating Mistral email sequences...")
    print(f"Step 3/3: Sending step 1 via Gmail...")
    try:
        result = run_full_outbound(
            company,
            dry_run=args.dry_run,
            send_now=not args.schedule_only,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Outbound failed: {exc}", file=sys.stderr)
        if "Gmail OAuth" in str(exc) or "gmail_oauth" in str(exc):
            print("Run once: python gmail_oauth.py", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))

    sent = result.get("sent", [])
    if args.dry_run:
        print(f"\nDry run complete for {company}. No emails were sent.")
    elif args.schedule_only:
        ensure_automatic_followups()
        print(f"\nScheduled {len(result.get('scheduled', []))} sequences for {company}.")
        print("Run `python send_outbound.py run --force` to send step 1 later.")
        print("Follow-ups at +1 and +3 days will send automatically once step 1 is sent.")
    else:
        ensure_automatic_followups()
        ok = [s for s in sent if s.get("status") == "sent"]
        failed = [s for s in sent if s.get("status") == "failed"]
        print(f"\nSent step 1 to {len(ok)} recruiter(s) at {company}.")
        if failed:
            print(f"Failed: {len(failed)}", file=sys.stderr)
            return 1
        print(
            "Follow-ups at +1 day and +3 days will send automatically "
            "Mon-Fri 8am-5pm PT."
        )
        if not is_cloud_configured():
            print(
                "Tip: free PC-off follow-ups via GitHub Actions: "
                "python cloud/deploy_github.py"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
