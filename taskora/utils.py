from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timezone
from pathlib import Path

APP_NAME = "Taskora"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def local_day_bounds(target: date | None = None) -> tuple[datetime, datetime]:
    target = target or datetime.now().date()
    start_local = datetime.combine(target, time.min).astimezone()
    end_local = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if end_local <= start_local:
        from datetime import timedelta
        end_local = end_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def seconds_between(start_iso: str, end_iso: str | None = None) -> int:
    start = parse_dt(start_iso)
    end = parse_dt(end_iso) if end_iso else utc_now()
    if not start or not end:
        return 0
    return max(0, int((end - start).total_seconds()))


def format_duration(total_seconds: int | float | None) -> str:
    total = max(0, int(total_seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def app_data_dir(custom: str | os.PathLike[str] | None = None) -> Path:
    if custom:
        return Path(custom).expanduser().resolve()
    env_home = os.environ.get("TASKORA_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def safe_filename(value: str, fallback: str = "untitled") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or fallback)[:120]


def normalize_process_name(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower().removesuffix(".exe")
