"""Mistral-powered outbound email copy generation."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mistralai.client import Mistral

from resume import SENDER_EMAIL, SENDER_NAME, get_resume_text

load_dotenv(Path(__file__).parent / ".env")

MODEL = "mistral-large-latest"


class MistralEmailError(RuntimeError):
    pass


def _client() -> Mistral:
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise MistralEmailError("MISTRAL_API_KEY is not set")
    return Mistral(api_key=api_key)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _ascii_email_text(text: str) -> str:
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def generate_email_sequence(
    *,
    company: str,
    recipient_name: str,
    recipient_title: str,
    role_priority: str,
) -> list[dict[str, str]]:
    resume_text = get_resume_text()
    first_name = recipient_name.split()[0] if recipient_name else "there"

    prompt = f"""You are writing a concise, professional recruiting outreach sequence for {SENDER_NAME}.

Sender email: {SENDER_EMAIL}
Target company: {company}
Recipient name: {recipient_name}
Recipient title: {recipient_title or "recruiter"}
Recipient role type: {role_priority}

Resume:
{resume_text}

Write a 3-email sequence as JSON with this exact shape:
{{
  "emails": [
    {{"step": 1, "subject": "...", "body": "..."}},
    {{"step": 2, "subject": "...", "body": "..."}},
    {{"step": 3, "subject": "...", "body": "..."}}
  ]
}}

Requirements:
- Email 1 (initial): mention resume is attached, include exactly 2 strong career highlights from the resume, explain who Henry is and why he is a strong fit for software engineering roles at {company}. Keep under 180 words.
- Email 2 (follow-up after 1 day with no response): brief, polite bump referencing the first note and resume. Under 90 words.
- Email 3 (follow-up after 3 days total with no response): final short follow-up, respectful and not pushy. Under 80 words.
- Use plain text only, no markdown.
- Use ASCII punctuation only: straight apostrophes, straight quotes, and regular hyphens.
- Address the recipient as {first_name} when possible.
- Sign off as {SENDER_NAME}.
- Do not invent employers, metrics, or projects not supported by the resume.
- Return valid JSON only.
"""

    response = _client().chat.complete(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        raise MistralEmailError("Mistral returned empty content")

    payload = _extract_json(content)
    emails = payload.get("emails")
    if not isinstance(emails, list) or len(emails) != 3:
        raise MistralEmailError(f"Expected 3 emails, got: {payload!r}")

    normalized: list[dict[str, str]] = []
    for item in emails:
        if not isinstance(item, dict):
            raise MistralEmailError(f"Invalid email item: {item!r}")
        step = int(item.get("step", 0))
        subject = _ascii_email_text(str(item.get("subject", ""))).strip()
        body = _ascii_email_text(str(item.get("body", ""))).strip()
        if not subject or not body:
            raise MistralEmailError(f"Missing subject/body in step {step}")
        normalized.append({"step": str(step), "subject": subject, "body": body})

    normalized.sort(key=lambda e: int(e["step"]))
    return normalized
