"""Business-hours scheduling helpers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from paths import ENV_FILE

load_dotenv(ENV_FILE)

DEFAULT_TZ = ZoneInfo(os.getenv("BUSINESS_TIMEZONE", "America/Los_Angeles"))
BUSINESS_START_HOUR = int(os.getenv("BUSINESS_HOUR_START", "9"))
BUSINESS_END_HOUR = int(os.getenv("BUSINESS_HOUR_END", "17"))


def _is_business_day(dt: datetime) -> bool:
    return dt.weekday() < 5


def _in_business_hours(dt: datetime) -> bool:
    return BUSINESS_START_HOUR <= dt.hour < BUSINESS_END_HOUR


def to_business_timezone(dt: datetime | None = None) -> datetime:
    if dt is None:
        dt = datetime.now(DEFAULT_TZ)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=DEFAULT_TZ)
    else:
        dt = dt.astimezone(DEFAULT_TZ)
    return dt


def next_business_slot(from_dt: datetime | None = None) -> datetime:
    dt = to_business_timezone(from_dt)

    while True:
        if not _is_business_day(dt):
            dt = dt.replace(
                hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            continue

        if dt.hour < BUSINESS_START_HOUR:
            return dt.replace(
                hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0
            )

        if dt.hour >= BUSINESS_END_HOUR:
            dt = dt.replace(
                hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            continue

        return dt.replace(second=0, microsecond=0)


def schedule_followup(base: datetime, days_after: int) -> datetime:
    target = base + timedelta(days=days_after)
    return next_business_slot(target)


def is_send_window_open(now: datetime | None = None) -> bool:
    dt = to_business_timezone(now)
    return _is_business_day(dt) and _in_business_hours(dt)
