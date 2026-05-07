"""SessionRecorder — persists a completed Responses-API call to the session table.

The response_id is provided by the caller (generated in the API layer before
the LiteLLM call so it can be embedded in streaming events). This module
only persists; it does not generate ids.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from gateway.ids import new_session_id
from gateway.logging_setup import get_logger
from gateway.session.store import SessionRecord


class _StoreLike(Protocol):
    async def insert(self, record: SessionRecord) -> None: ...


class _ColdLike(Protocol):
    async def put(self, payload: dict[str, Any]) -> str: ...


_log = get_logger(__name__)


class SessionRecorder:
    def __init__(
        self,
        *,
        store: _StoreLike,
        cold_storage: _ColdLike | None,
        ttl_days: int,
        threshold_bytes: int,
    ) -> None:
        self._store = store
        self._cold = cold_storage
        self._ttl = timedelta(days=ttl_days)
        self._threshold = threshold_bytes

    async def record(
        self,
        *,
        response_id: str,
        original_request: dict[str, Any],
        response_payload: dict[str, Any],
        provider: str,
        model: str,
        session_id: str | None,
        parent_id: str | None,
        store_flag: bool,
    ) -> None:
        """Persist a finished call. No-op if store_flag is False.

        The caller is responsible for generating `response_id` (typically
        in the HTTP layer, before the LLM call, so streaming events can
        carry the gateway-assigned id from response.created onward).
        """
        if not store_flag:
            return

        sid = session_id or new_session_id()
        now = datetime.now(UTC)
        ttl_at = now + self._ttl

        rec = SessionRecord(
            id=response_id,
            session_id=sid,
            parent_id=parent_id,
            model=model,
            provider=provider,
            input_json=original_request,
            output_json=response_payload,
            usage_json=response_payload.get("usage"),
            cold_storage_key=None,
            created_at=now,
            ttl_at=ttl_at,
        )

        size = len(json.dumps(original_request)) + len(json.dumps(response_payload))
        if self._cold is not None and size > self._threshold:
            try:
                key = await self._cold.put({"input": original_request, "output": response_payload})
                rec.input_json = None
                rec.output_json = None
                rec.cold_storage_key = key
            except Exception as exc:
                _log.warning(
                    "cold_storage_write_failed_falling_back_inline",
                    error=str(exc),
                    response_id=response_id,
                )

        await self._store.insert(rec)
