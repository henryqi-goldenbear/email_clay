"""SQLite persistence for companies and contacts."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import CONTACTS_DB

DEFAULT_DB_PATH = CONTACTS_DB


@dataclass
class Contact:
    company: str
    company_identifier: str
    name: str
    title: str
    email: str | None
    role_priority: str
    linkedin_url: str | None = None
    clay_search_id: str | None = None
    raw_data: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                identifier TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(name, identifier)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                title TEXT,
                email TEXT,
                role_priority TEXT NOT NULL,
                linkedin_url TEXT,
                clay_search_id TEXT,
                raw_data TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbound_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                contact_email TEXT NOT NULL,
                contact_name TEXT,
                contact_title TEXT,
                role_priority TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                UNIQUE(company, contact_email)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbound_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                step INTEGER NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                sent_at TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                error TEXT,
                FOREIGN KEY (campaign_id) REFERENCES outbound_campaigns(id),
                UNIQUE(campaign_id, step)
            )
            """
        )
        conn.commit()


def upsert_company(name: str, identifier: str, db_path: Path = DEFAULT_DB_PATH) -> int:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO companies (name, identifier, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name, identifier) DO UPDATE SET
                created_at = excluded.created_at
            """,
            (name, identifier, _utc_now()),
        )
        row = conn.execute(
            "SELECT id FROM companies WHERE name = ? AND identifier = ?",
            (name, identifier),
        ).fetchone()
        conn.commit()
        if not row:
            raise RuntimeError(f"Failed to upsert company {name}")
        return int(row[0])


def save_contacts(
    company_id: int,
    contacts: list[Contact],
    db_path: Path = DEFAULT_DB_PATH,
) -> list[int]:
    init_db(db_path)
    ids: list[int] = []
    with sqlite3.connect(db_path) as conn:
        for contact in contacts:
            cursor = conn.execute(
                """
                INSERT INTO contacts (
                    company_id, name, title, email, role_priority,
                    linkedin_url, clay_search_id, raw_data, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    company_id,
                    contact.name,
                    contact.title,
                    contact.email,
                    contact.role_priority,
                    contact.linkedin_url,
                    contact.clay_search_id,
                    contact.raw_data,
                    _utc_now(),
                ),
            )
            ids.append(int(cursor.lastrowid))
        conn.commit()
    return ids


def get_contacts_for_company(
    company_name: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                c.name AS company_name,
                c.identifier AS company_identifier,
                ct.name,
                ct.title,
                ct.email,
                ct.role_priority,
                ct.linkedin_url,
                ct.created_at
            FROM contacts ct
            JOIN companies c ON c.id = ct.company_id
            WHERE c.name = ?
            ORDER BY ct.id ASC
            """,
            (company_name,),
        ).fetchall()
        return [dict(row) for row in rows]


def create_or_get_campaign(
    *,
    company: str,
    contact_email: str,
    contact_name: str,
    contact_title: str,
    role_priority: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO outbound_campaigns (
                company, contact_email, contact_name, contact_title,
                role_priority, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(company, contact_email) DO UPDATE SET
                contact_name = excluded.contact_name,
                contact_title = excluded.contact_title,
                role_priority = excluded.role_priority
            """,
            (
                company,
                contact_email,
                contact_name,
                contact_title,
                role_priority,
                _utc_now(),
            ),
        )
        row = conn.execute(
            """
            SELECT id FROM outbound_campaigns
            WHERE company = ? AND contact_email = ?
            """,
            (company, contact_email),
        ).fetchone()
        conn.commit()
        if not row:
            raise RuntimeError(f"Failed to create campaign for {contact_email}")
        return int(row[0])


def schedule_campaign_messages(
    campaign_id: int,
    messages: list[dict[str, str]],
    db_path: Path = DEFAULT_DB_PATH,
) -> list[int]:
    init_db(db_path)
    ids: list[int] = []
    with sqlite3.connect(db_path) as conn:
        for message in messages:
            cursor = conn.execute(
                """
                INSERT INTO outbound_messages (
                    campaign_id, step, subject, body, scheduled_at, status
                ) VALUES (?, ?, ?, ?, ?, 'scheduled')
                ON CONFLICT(campaign_id, step) DO UPDATE SET
                    subject = excluded.subject,
                    body = excluded.body,
                    scheduled_at = excluded.scheduled_at,
                    status = CASE
                        WHEN outbound_messages.status = 'sent' THEN outbound_messages.status
                        ELSE 'scheduled'
                    END,
                    error = NULL
                """,
                (
                    campaign_id,
                    int(message["step"]),
                    message["subject"],
                    message["body"],
                    message["scheduled_at"],
                ),
            )
            ids.append(int(cursor.lastrowid))
        conn.commit()
    return ids


def get_due_messages(
    company: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    init_db(db_path)
    now = _utc_now()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        query = """
            SELECT
                m.id AS message_id,
                m.step,
                m.subject,
                m.body,
                m.scheduled_at,
                c.id AS campaign_id,
                c.company,
                c.contact_email,
                c.contact_name,
                c.status AS campaign_status
            FROM outbound_messages m
            JOIN outbound_campaigns c ON c.id = m.campaign_id
            WHERE m.status = 'scheduled'
              AND m.scheduled_at <= ?
              AND c.status = 'active'
              AND (
                m.step = 1
                OR EXISTS (
                  SELECT 1 FROM outbound_messages prev
                  WHERE prev.campaign_id = m.campaign_id
                    AND prev.step = m.step - 1
                    AND prev.status = 'sent'
                )
              )
        """
        params: list[Any] = [now]
        if company:
            query += " AND c.company = ?"
            params.append(company)
        query += " ORDER BY m.scheduled_at ASC, m.step ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def mark_company_step1_due(
    company: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    init_db(db_path)
    now = _utc_now()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE outbound_messages
            SET scheduled_at = ?, status = 'scheduled', error = NULL
            WHERE step = 1
              AND campaign_id IN (
                SELECT id FROM outbound_campaigns WHERE company = ?
              )
              AND status IN ('scheduled', 'failed')
            """,
            (now, company),
        )
        conn.commit()
        return int(cursor.rowcount)


def mark_message_sent(message_id: int, db_path: Path = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE outbound_messages
            SET status = 'sent', sent_at = ?, error = NULL
            WHERE id = ?
            """,
            (_utc_now(), message_id),
        )
        conn.commit()


def mark_message_failed(
    message_id: int,
    error: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE outbound_messages
            SET status = 'failed', error = ?
            WHERE id = ?
            """,
            (error, message_id),
        )
        conn.commit()


def skip_remaining_campaign_messages(
    campaign_id: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE outbound_messages
            SET status = 'skipped'
            WHERE campaign_id = ? AND status = 'scheduled'
            """,
            (campaign_id,),
        )
        conn.commit()


def mark_campaign_replied(campaign_id: int, db_path: Path = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE outbound_campaigns SET status = 'replied' WHERE id = ?",
            (campaign_id,),
        )
        conn.execute(
            """
            UPDATE outbound_messages
            SET status = 'skipped'
            WHERE campaign_id = ? AND status = 'scheduled'
            """,
            (campaign_id,),
        )
        conn.commit()
