"""Tests for the in-memory ColdStorage implementation (used in tests + dev)."""

from __future__ import annotations

import pytest

from gateway.errors import ColdStorageUnavailableError
from gateway.storage.cold import ColdStorage, InMemoryColdStorage


def test_inmem_storage_roundtrip() -> None:
    cs: ColdStorage = InMemoryColdStorage()
    payload = {"input": [{"role": "user", "content": "hi"}], "output": [{"type": "message"}]}
    key = cs.put_sync(payload)  # InMemory provides sync helpers for tests
    fetched = cs.get_sync(key)
    assert fetched == payload


def test_inmem_get_missing_raises() -> None:
    cs = InMemoryColdStorage()
    with pytest.raises(ColdStorageUnavailableError):
        cs.get_sync("nonexistent-key")


async def test_inmem_storage_async_api() -> None:
    cs: ColdStorage = InMemoryColdStorage()
    key = await cs.put({"a": 1})
    fetched = await cs.get(key)
    assert fetched == {"a": 1}
