"""Integration tests for SessionStore against SQLite (in-memory)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gateway.session.models import Base
from gateway.session.store import SessionRecord, SessionStore


@pytest.fixture
async def store() -> SessionStore:
    s = SessionStore("sqlite+aiosqlite:///:memory:")
    await s.create_schema(Base.metadata)
    return s


async def test_insert_then_get_by_id(store: SessionStore) -> None:
    rec = SessionRecord(
        id="resp_a",
        session_id="sess_1",
        parent_id=None,
        model="deepseek-chat",
        provider="deepseek",
        input_json={"input": "hi"},
        output_json={"output": [{"type": "message"}]},
        usage_json=None,
        cold_storage_key=None,
        created_at=datetime.now(UTC),
        ttl_at=None,
    )
    await store.insert(rec)
    got = await store.get_by_id("resp_a")
    assert got is not None
    assert got.id == "resp_a"
    assert got.model == "deepseek-chat"


async def test_get_by_id_missing_returns_none(store: SessionStore) -> None:
    assert await store.get_by_id("resp_nope") is None


async def test_list_by_session_id_returns_chain_in_order(store: SessionStore) -> None:
    base = datetime.now(UTC)
    for i in range(3):
        await store.insert(
            SessionRecord(
                id=f"resp_{i}",
                session_id="sess_chain",
                parent_id=f"resp_{i - 1}" if i > 0 else None,
                model="deepseek-chat",
                provider="deepseek",
                input_json={"input": f"msg {i}"},
                output_json={"output": []},
                usage_json=None,
                cold_storage_key=None,
                created_at=base + timedelta(seconds=i),
                ttl_at=None,
            )
        )
    chain = await store.list_by_session_id("sess_chain")
    assert [r.id for r in chain] == ["resp_0", "resp_1", "resp_2"]


async def test_delete_expired_removes_only_expired(store: SessionStore) -> None:
    now = datetime.now(UTC)
    await store.insert(
        SessionRecord(
            id="resp_expired",
            session_id="s1",
            parent_id=None,
            model="m",
            provider="p",
            input_json=None,
            output_json=None,
            usage_json=None,
            cold_storage_key=None,
            created_at=now - timedelta(days=10),
            ttl_at=now - timedelta(days=1),
        )
    )
    await store.insert(
        SessionRecord(
            id="resp_alive",
            session_id="s2",
            parent_id=None,
            model="m",
            provider="p",
            input_json=None,
            output_json=None,
            usage_json=None,
            cold_storage_key=None,
            created_at=now,
            ttl_at=now + timedelta(days=1),
        )
    )
    deleted = await store.delete_expired(as_of=now)
    assert deleted == 1
    assert await store.get_by_id("resp_expired") is None
    assert await store.get_by_id("resp_alive") is not None
