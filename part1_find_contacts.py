"""Part 1: Find priority contacts at a company via Clay."""

from __future__ import annotations

import json
import re
from typing import Any

from clay_client import ClayMCPClient
from db import Contact, save_contacts, upsert_company

MAX_CONTACTS = 4

ROLE_SEARCHES: list[tuple[str, list[str]]] = [
    (
        "technical_recruiter",
        [
            "technical recruiter",
            "tech recruiter",
            "technical sourcer",
            "talent acquisition",
            "recruiter",
        ],
    ),
    (
        "hiring_manager",
        [
            "hiring manager",
            "engineering manager",
            "head of engineering",
            "vp engineering",
            "director of engineering",
            "engineering lead",
        ],
    ),
    (
        "founder",
        [
            "founder",
            "co-founder",
            "cofounder",
            "ceo",
            "chief executive officer",
        ],
    ),
]

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip()
    if EMAIL_PATTERN.fullmatch(email):
        return email
    return None


def normalize_company_identifier(company: str) -> str:
    company = company.strip().lower()
    company = re.sub(r"^https?://", "", company)
    company = company.rstrip("/")
    if "." not in company:
        return f"{company}.com"
    return company


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _pick_first(values: list[Any]) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _extract_contacts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("contacts", "results", "people", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    if any(k in payload for k in ("name", "fullName", "email", "jobTitle", "title")):
        return [payload]

    return []


def _contact_name(contact: dict[str, Any]) -> str | None:
    return _pick_first(
        [
            contact.get("name"),
            contact.get("fullName"),
            contact.get("full_name"),
            " ".join(
                part
                for part in [
                    contact.get("firstName") or contact.get("first_name"),
                    contact.get("lastName") or contact.get("last_name"),
                ]
                if part
            ).strip()
            or None,
        ]
    )


def _contact_title(contact: dict[str, Any]) -> str | None:
    return _pick_first(
        [
            contact.get("title"),
            contact.get("jobTitle"),
            contact.get("job_title"),
            contact.get("latest_experience_title"),
            contact.get("headline"),
            contact.get("currentTitle"),
        ]
    )


def _contact_email(contact: dict[str, Any]) -> str | None:
    email = _valid_email(contact.get("email"))
    if email:
        return email

    enrichments = contact.get("enrichments")
    if isinstance(enrichments, list):
        for item in enrichments:
            if not isinstance(item, dict):
                continue
            if item.get("name") == "Email" and item.get("state") == "completed":
                value = _valid_email(item.get("value"))
                if value:
                    return value

    emails = contact.get("emails")
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, str):
                value = _valid_email(item)
                if value:
                    return value
            if isinstance(item, dict):
                value = _valid_email(item.get("email") or item.get("value"))
                if value:
                    return value

    data_points = contact.get("dataPoints") or contact.get("data_points")
    if isinstance(data_points, list):
        for point in data_points:
            if not isinstance(point, dict):
                continue
            if point.get("type") == "Email":
                value = _valid_email(point.get("value") or point.get("email"))
                if value:
                    return value

    return None


def _contact_linkedin(contact: dict[str, Any]) -> str | None:
    return _pick_first(
        [
            contact.get("url"),
            contact.get("linkedinUrl"),
            contact.get("linkedin_url"),
            contact.get("linkedInUrl"),
            contact.get("profileUrl"),
            contact.get("profile_url"),
        ]
    )


def _search_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("searchId", "search_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _dedupe_key(contact: dict[str, Any]) -> str:
    email = (_contact_email(contact) or "").lower()
    if email:
        return f"email:{email}"
    name = (_contact_name(contact) or "").lower()
    title = (_contact_title(contact) or "").lower()
    return f"name:{name}|title:{title}"


DEMO_CONTACTS: dict[str, list[Contact]] = {
    "openai": [
        Contact(
            company="OpenAI",
            company_identifier="openai.com",
            name="Demo Technical Recruiter",
            title="Technical Recruiter",
            email="recruiter.demo@openai.com",
            role_priority="technical_recruiter",
            linkedin_url="https://linkedin.com/in/demo-recruiter",
        ),
        Contact(
            company="OpenAI",
            company_identifier="openai.com",
            name="Demo Hiring Manager",
            title="Engineering Manager",
            email="hiring.demo@openai.com",
            role_priority="hiring_manager",
            linkedin_url="https://linkedin.com/in/demo-hiring-manager",
        ),
        Contact(
            company="OpenAI",
            company_identifier="openai.com",
            name="Demo Founder",
            title="Co-founder",
            email="founder.demo@openai.com",
            role_priority="founder",
            linkedin_url="https://linkedin.com/in/demo-founder",
        ),
    ],
}


def find_priority_contacts(
    company_name: str,
    company_identifier: str | None = None,
    max_contacts: int = MAX_CONTACTS,
) -> list[Contact]:
    identifier = company_identifier or normalize_company_identifier(company_name)
    found: list[Contact] = []
    seen: set[str] = set()

    with ClayMCPClient() as clay:
        for role_priority, keywords in ROLE_SEARCHES:
            if len(found) >= max_contacts:
                break

            payload = clay.find_contacts_at_company(identifier, keywords)
            search_id = _search_id(payload)

            if search_id:
                enriched = clay.enrich_contacts_with_emails(payload)
                contacts = _extract_contacts(enriched)
                if not contacts:
                    contacts = _extract_contacts(payload)
            else:
                contacts = _extract_contacts(payload)

            for raw in contacts:
                if len(found) >= max_contacts:
                    break

                key = _dedupe_key(raw)
                if key in seen:
                    continue
                seen.add(key)

                name = _contact_name(raw)
                if not name:
                    continue

                found.append(
                    Contact(
                        company=company_name,
                        company_identifier=identifier,
                        name=name,
                        title=_contact_title(raw) or "",
                        email=_contact_email(raw),
                        role_priority=role_priority,
                        linkedin_url=_contact_linkedin(raw),
                        clay_search_id=search_id,
                        raw_data=json.dumps(raw),
                    )
                )

    return found


def run_part1(
    company_name: str,
    company_identifier: str | None = None,
    max_contacts: int = MAX_CONTACTS,
    demo: bool = False,
) -> dict[str, Any]:
    identifier = company_identifier or normalize_company_identifier(company_name)

    if demo:
        demo_key = company_name.strip().lower()
        contacts = list(DEMO_CONTACTS.get(demo_key, DEMO_CONTACTS["openai"]))[:max_contacts]
        for contact in contacts:
            contact.company = company_name
            contact.company_identifier = identifier
    else:
        contacts = find_priority_contacts(company_name, identifier, max_contacts)

    company_id = upsert_company(company_name, identifier)
    save_contacts(company_id, contacts)

    return {
        "company": company_name,
        "company_identifier": identifier,
        "company_id": company_id,
        "contacts_found": len(contacts),
        "contacts": [
            {
                "name": c.name,
                "title": c.title,
                "email": c.email,
                "role_priority": c.role_priority,
                "linkedin_url": c.linkedin_url,
            }
            for c in contacts
        ],
    }
