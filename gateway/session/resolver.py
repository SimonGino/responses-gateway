"""SessionResolver — intercept previous_response_id and rebuild full message history.

Strategy: rather than passing previous_response_id down to LiteLLM (whose
SessionHandler requires the LiteLLM Proxy spend_logs DB), we resolve it ourselves
from our own session table and prepend reconstructed messages to the current
request input.

Walking strategy: iterate up the `parent_id` chain from the given
previous_response_id. Do NOT use `session_id` for retrieval — branched siblings
share the same session_id, but the chained linear history must follow parent_id
pointers only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from gateway.errors import (
    ColdStorageUnavailableError,
    PreviousResponseExpiredError,
    PreviousResponseNotFoundError,
    PreviousResponseProviderMismatchError,
)
from gateway.session.store import SessionRecord


class _StoreLike(Protocol):
    async def get_by_id(self, response_id: str) -> SessionRecord | None: ...


class _ColdLike(Protocol):
    async def get(self, key: str) -> dict[str, Any]: ...


@dataclass
class ResolvedRequest:
    """Request after previous_response_id resolution."""

    request: dict[str, Any]
    session_id: str | None
    parent_id: str | None


class SessionResolver:
    def __init__(self, *, store: _StoreLike, cold_storage: _ColdLike | None) -> None:
        self._store = store
        self._cold = cold_storage

    async def resolve(self, request: dict[str, Any], *, current_provider: str) -> ResolvedRequest:
        prev_id = request.get("previous_response_id")
        if not prev_id:
            return ResolvedRequest(request=request, session_id=None, parent_id=None)

        parent = await self._store.get_by_id(prev_id)
        if parent is None:
            raise PreviousResponseNotFoundError(previous_response_id=prev_id)
        ttl = parent.ttl_at
        if ttl is not None and ttl.tzinfo is None:
            # SQLite stores datetimes as naive UTC; make aware so we can compare.
            ttl = ttl.replace(tzinfo=UTC)
        if ttl is not None and ttl < datetime.now(UTC):
            raise PreviousResponseExpiredError(previous_response_id=prev_id)
        if parent.provider != current_provider:
            raise PreviousResponseProviderMismatchError(
                parent_provider=parent.provider, current_provider=current_provider
            )

        chain = await self._walk_parent_chain(prev_id)
        history = await self._reconstruct_messages(chain)

        current_input = request.get("input", [])
        new_input = history + self._normalize_current_input(current_input)
        new_request = {**request, "input": new_input}
        new_request.pop("previous_response_id", None)

        return ResolvedRequest(request=new_request, session_id=parent.session_id, parent_id=prev_id)

    async def _walk_parent_chain(self, start_id: str) -> list[SessionRecord]:
        """Walk parent_id pointers to root, return chain in chronological order."""
        chain: list[SessionRecord] = []
        visited: set[str] = set()
        cur: str | None = start_id
        while cur and cur not in visited:
            visited.add(cur)
            row = await self._store.get_by_id(cur)
            if row is None:
                break
            chain.append(row)
            cur = row.parent_id
        chain.reverse()
        return chain

    async def _reconstruct_messages(self, chain: list[SessionRecord]) -> list[dict[str, Any]]:
        """Build chat-completions-style messages from a walked chain.

        Per OpenAI Responses API: previous_response_id does NOT inherit old
        `instructions`. We therefore extract only the user-facing input items
        from each historical row (skipping any system messages produced from
        past `instructions`), plus the row's output messages.
        """
        messages: list[dict[str, Any]] = []
        for row in chain:
            input_payload = await self._payload(row, field="input")
            output_payload = await self._payload(row, field="output")
            messages.extend(self._extract_non_system_input(input_payload.get("input", [])))
            for item in output_payload.get("output", []):
                if isinstance(item, dict) and item.get("type") == "message":
                    messages.append({"role": "assistant", "content": item.get("content", [])})
                elif isinstance(item, dict) and item.get("type") == "function_call":
                    messages.append(item)
        return messages

    async def _payload(self, row: SessionRecord, *, field: str) -> dict[str, Any]:
        if row.cold_storage_key:
            if self._cold is None:
                # Use raise (not assert) so 'python -O' still produces a clean
                # 503 instead of an uncaught AttributeError on self._cold.get(...)
                raise ColdStorageUnavailableError(
                    f"row {row.id} has cold_storage_key but cold storage is not configured"
                )
            full = await self._cold.get(row.cold_storage_key)
            return {field: full.get(field, [])}
        if field == "input":
            return row.input_json or {"input": []}
        return row.output_json or {"output": []}

    @staticmethod
    def _normalize_current_input(current: Any) -> list[dict[str, Any]]:
        if isinstance(current, str):
            return [{"role": "user", "content": current}]
        if isinstance(current, list):
            return list(current)
        if isinstance(current, dict):
            return [current]
        return []

    @staticmethod
    def _extract_non_system_input(items: Any) -> list[dict[str, Any]]:
        """Filter out system messages from a stored Responses-API input.

        Past `instructions` (which in chat form became system messages) must
        not bleed into the new request's system prompt.
        """
        normalized = SessionResolver._normalize_current_input(items)
        out: list[dict[str, Any]] = []
        for item in normalized:
            if isinstance(item, dict) and item.get("role") == "system":
                continue
            out.append(item)
        return out
