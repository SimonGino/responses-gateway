"""Tests for SessionResolver — intercepts previous_response_id and rebuilds messages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from gateway.errors import (
    ColdStorageUnavailableError,
    PreviousResponseExpiredError,
    PreviousResponseNotFoundError,
    PreviousResponseProviderMismatchError,
)
from gateway.session.resolver import SessionResolver
from gateway.session.store import SessionRecord


class FakeStore:
    def __init__(self, records: list[SessionRecord]) -> None:
        self._by_id = {r.id: r for r in records}

    async def get_by_id(self, response_id: str) -> SessionRecord | None:
        return self._by_id.get(response_id)


class FakeCold:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self._payloads = payloads

    async def get(self, key: str) -> dict[str, Any]:
        return self._payloads[key]


def _row(
    id_: str,
    session_id: str,
    parent_id: str | None,
    *,
    provider: str = "deepseek",
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    ttl_at: datetime | None = None,
) -> SessionRecord:
    return SessionRecord(
        id=id_,
        session_id=session_id,
        parent_id=parent_id,
        model="deepseek-chat",
        provider=provider,
        input_json=input_json or {"input": "default"},
        output_json=output_json
        or {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]},
        usage_json=None,
        cold_storage_key=None,
        created_at=datetime.now(UTC),
        ttl_at=ttl_at,
    )


async def test_no_previous_response_id_passes_through() -> None:
    resolver = SessionResolver(store=FakeStore([]), cold_storage=None)
    req: dict[str, Any] = {"input": "hello", "model": "deepseek-chat"}
    resolved = await resolver.resolve(req, current_provider="deepseek")
    assert resolved.request == req
    assert resolved.session_id is None
    assert resolved.parent_id is None


async def test_resolves_chain_into_messages_and_drops_previous_response_id() -> None:
    history = [
        _row(
            "r1",
            "s1",
            None,
            input_json={"input": "first user"},
            output_json={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "first asst"}]}
                ]
            },
        ),
        _row(
            "r2",
            "s1",
            "r1",
            input_json={"input": "second user"},
            output_json={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "second asst"}]}
                ]
            },
        ),
    ]
    resolver = SessionResolver(store=FakeStore(history), cold_storage=None)
    req = {"input": "third user", "model": "deepseek-chat", "previous_response_id": "r2"}
    resolved = await resolver.resolve(req, current_provider="deepseek")

    assert "previous_response_id" not in resolved.request
    assert resolved.session_id == "s1"
    assert resolved.parent_id == "r2"
    new_input = resolved.request["input"]
    assert isinstance(new_input, list)
    assert len(new_input) == 5  # r1.input + r1.output + r2.input + r2.output + current = 5


async def test_unknown_previous_response_id_raises_404() -> None:
    resolver = SessionResolver(store=FakeStore([]), cold_storage=None)
    with pytest.raises(PreviousResponseNotFoundError):
        await resolver.resolve(
            {"input": "x", "model": "m", "previous_response_id": "resp_missing"},
            current_provider="deepseek",
        )


async def test_expired_previous_response_id_raises_410() -> None:
    expired = _row("r1", "s1", None, ttl_at=datetime.now(UTC) - timedelta(days=1))
    resolver = SessionResolver(store=FakeStore([expired]), cold_storage=None)
    with pytest.raises(PreviousResponseExpiredError):
        await resolver.resolve(
            {"input": "x", "model": "deepseek-chat", "previous_response_id": "r1"},
            current_provider="deepseek",
        )


async def test_provider_mismatch_raises_409() -> None:
    history = [_row("r1", "s1", None, provider="dashscope")]
    resolver = SessionResolver(store=FakeStore(history), cold_storage=None)
    with pytest.raises(PreviousResponseProviderMismatchError):
        await resolver.resolve(
            {"input": "x", "model": "deepseek-chat", "previous_response_id": "r1"},
            current_provider="deepseek",
        )


async def test_walk_chain_ignores_branch_siblings() -> None:
    """Two children of the same parent must not bleed into each other's chains."""
    rows = [
        _row(
            "root",
            "s1",
            None,
            output_json={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "root reply"}]}
                ]
            },
        ),
        _row(
            "branch_a",
            "s1",
            "root",
            output_json={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "branch a"}]}
                ]
            },
        ),
        _row(
            "branch_b",
            "s1",
            "root",
            output_json={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "branch b"}]}
                ]
            },
        ),
    ]
    resolver = SessionResolver(store=FakeStore(rows), cold_storage=None)
    req = {"input": "follow-up", "model": "deepseek-chat", "previous_response_id": "branch_a"}
    resolved = await resolver.resolve(req, current_provider="deepseek")
    rendered = str(resolved.request["input"])
    assert "branch a" in rendered
    assert "branch b" not in rendered  # the sibling must NOT appear


async def test_old_instructions_dropped_from_history() -> None:
    """Past `instructions` must not become system messages in the rebuilt history."""
    history = [
        _row(
            "r1",
            "s1",
            None,
            input_json={
                "input": [
                    {"role": "system", "content": "old system prompt — should be dropped"},
                    {"role": "user", "content": "hello"},
                ],
            },
        )
    ]
    resolver = SessionResolver(store=FakeStore(history), cold_storage=None)
    resolved = await resolver.resolve(
        {"input": "follow-up", "model": "deepseek-chat", "previous_response_id": "r1"},
        current_provider="deepseek",
    )
    new_input_str = str(resolved.request["input"])
    assert "old system prompt" not in new_input_str
    assert "hello" in new_input_str


# ---------- Cold storage path ----------


async def test_cold_storage_payload_retrieved_when_key_set() -> None:
    """When a row's input/output is offloaded to cold storage, _payload reads it."""
    cold_key = "cold-abc"
    cold_payload = {
        "input": {"input": [{"role": "user", "content": "from cold"}]},
        "output": {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "from cold"}]}
            ]
        },
    }
    row = SessionRecord(
        id="r1",
        session_id="s1",
        parent_id=None,
        model="deepseek-chat",
        provider="deepseek",
        input_json=None,  # offloaded
        output_json=None,  # offloaded
        usage_json=None,
        cold_storage_key=cold_key,
        created_at=datetime.now(UTC),
        ttl_at=None,
    )
    resolver = SessionResolver(
        store=FakeStore([row]), cold_storage=FakeCold({cold_key: cold_payload})
    )
    resolved = await resolver.resolve(
        {"input": "follow-up", "model": "deepseek-chat", "previous_response_id": "r1"},
        current_provider="deepseek",
    )
    rendered = str(resolved.request["input"])
    assert "from cold" in rendered


async def test_cold_storage_required_but_missing_raises_503() -> None:
    """If a row references cold storage but the gateway has none configured,
    raise ColdStorageUnavailableError (503) instead of an AttributeError. The
    raise must NOT be an `assert` so it survives 'python -O'."""
    row = SessionRecord(
        id="r1",
        session_id="s1",
        parent_id=None,
        model="deepseek-chat",
        provider="deepseek",
        input_json=None,
        output_json=None,
        usage_json=None,
        cold_storage_key="some-key",
        created_at=datetime.now(UTC),
        ttl_at=None,
    )
    resolver = SessionResolver(store=FakeStore([row]), cold_storage=None)
    with pytest.raises(ColdStorageUnavailableError):
        await resolver.resolve(
            {"input": "x", "model": "deepseek-chat", "previous_response_id": "r1"},
            current_provider="deepseek",
        )
