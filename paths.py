"""Project and runtime data paths (local project dir or cloud /data volume)."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
DATA_DIR = Path(os.getenv("CLAY_OUTBOUND_DATA_DIR", PROJECT_DIR)).resolve()

CONTACTS_DB = DATA_DIR / "contacts.db"
GMAIL_TOKENS = DATA_DIR / ".gmail_tokens.json"
RESUME_PDF = DATA_DIR / "henry_swe (4).pdf"
RESUME_TEXT_CACHE = DATA_DIR / "resume_text.txt"
SCHEDULER_LOG = DATA_DIR / "scheduler.log"
ENV_FILE = DATA_DIR / ".env" if (DATA_DIR / ".env").exists() else PROJECT_DIR / ".env"
