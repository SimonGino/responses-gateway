"""ID generators using uuid7 (time-sortable)."""

from __future__ import annotations

from uuid_extensions import uuid7str as _uuid7str  # type: ignore[import-untyped]


def new_response_id() -> str:
    """Generate a new Responses API id (`resp_<uuid7>`)."""
    return f"resp_{_uuid7str()}"


def new_session_id() -> str:
    """Generate a new session/thread id (raw uuid7 string)."""
    return str(_uuid7str())


def new_request_id() -> str:
    """Generate a new HTTP-level request correlation id."""
    return str(_uuid7str())
