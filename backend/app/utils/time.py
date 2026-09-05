"""Shared time helper. SQLite DATETIME drops tzinfo, so the DB layer uses naive
UTC everywhere (arithmetic stays safe); JSON/logs use aware ISO strings."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
