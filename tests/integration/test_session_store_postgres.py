"""Same tests as SQLite version, but against a real Postgres (skip if not available)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from gateway.session.models import Base
from gateway.session.store import SessionStore

POSTGRES_URL = os.getenv("GATEWAY_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL or os.getenv("GATEWAY_TEST_STORAGE", "sqlite") != "postgres",
    reason="Postgres URL not configured",
)


@pytest.fixture
async def store() -> AsyncIterator[SessionStore]:
    assert POSTGRES_URL  # for mypy
    s = SessionStore(POSTGRES_URL)
    await s.create_schema(Base.metadata)
    yield s
    # Drop tables between tests
    async with s._engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await s.close()


# Re-import the SQLite test cases to get coverage on Postgres too
from tests.integration.test_session_store_sqlite import (  # noqa: E402, F401
    test_delete_expired_removes_only_expired,
    test_get_by_id_missing_returns_none,
    test_insert_then_get_by_id,
    test_list_by_session_id_returns_chain_in_order,
)
