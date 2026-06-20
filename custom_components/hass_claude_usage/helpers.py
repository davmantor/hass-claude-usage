"""Shared helpers for Claude Usage."""

from __future__ import annotations

from datetime import datetime


def parse_oauth_code(code: str, expected_state: str | None) -> str | None:
    """Return the OAuth code only when the callback state matches."""
    auth_code, separator, state = code.partition("#")
    if expected_state and (not separator or state != expected_state):
        return None
    return auth_code


def parse_timestamp(value: str) -> datetime | None:
    """Parse an ISO timestamp into a timezone-aware datetime."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
