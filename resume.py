"""Resume loading for outbound email generation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from paths import RESUME_PDF, RESUME_TEXT_CACHE

SENDER_NAME = "Henry Qi"
SENDER_EMAIL = "henryqi@berkeley.edu"
SENDER_PHONE = "916-693-0784"


@lru_cache(maxsize=1)
def get_resume_text() -> str:
    if RESUME_TEXT_CACHE.exists():
        return RESUME_TEXT_CACHE.read_text(encoding="utf-8")

    if not RESUME_PDF.exists():
        raise FileNotFoundError(f"Resume not found: {RESUME_PDF}")

    from pypdf import PdfReader

    reader = PdfReader(str(RESUME_PDF))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    RESUME_TEXT_CACHE.write_text(text, encoding="utf-8")
    return text


def get_resume_path() -> Path:
    if not RESUME_PDF.exists():
        raise FileNotFoundError(f"Resume not found: {RESUME_PDF}")
    return RESUME_PDF
