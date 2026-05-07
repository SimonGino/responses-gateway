"""Tests for SessionRecorder — persists new responses post-call."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from gateway.session.recorder import SessionRecorder
from gateway.session.store import SessionRecord
from gateway.storage.cold import InMemoryColdStorage


class CapturingStore:
    def __init__(self) -> None:
        self.records: list[SessionRecord] = []

    async def insert(self, rec: SessionRecord) -> None:
        self.records.append(rec)


async def test_recorder_stores_new_session_when_no_parent() -> None:
    store = CapturingStore()
    recorder = SessionRecorder(
        store=store, cold_storage=None, ttl_days=30, threshold_bytes=1_048_576
    )
    await recorder.record(
        response_id="resp_provided_xxx",
        original_request={"input": "hi", "model": "deepseek-chat"},
        response_payload={
            "id": "ignored",
            "output": [{"type": "message"}],
            "usage": {"input_tokens": 5},
        },
        provider="deepseek",
        model="deepseek-chat",
        session_id=None,
        parent_id=None,
        store_flag=True,
    )
    assert len(store.records) == 1
    rec = store.records[0]
    assert rec.id == "resp_provided_xxx"
    assert rec.parent_id is None
    assert rec.session_id  # newly generated
    assert rec.input_json == {"input": "hi", "model": "deepseek-chat"}
    assert rec.cold_storage_key is None
    assert rec.ttl_at is not None
    assert rec.ttl_at > datetime.now(UTC) + timedelta(days=29)


async def test_recorder_inherits_session_id_from_chain() -> None:
    store = CapturingStore()
    recorder = SessionRecorder(
        store=store, cold_storage=None, ttl_days=30, threshold_bytes=1_048_576
    )
    await recorder.record(
        response_id="resp_chained_xxx",
        original_request={"input": "msg2"},
        response_payload={"output": []},
        provider="deepseek",
        model="m",
        session_id="sess_existing",
        parent_id="resp_prev",
        store_flag=True,
    )
    rec = store.records[0]
    assert rec.session_id == "sess_existing"
    assert rec.parent_id == "resp_prev"


async def test_recorder_skips_when_store_false() -> None:
    """store=False is a pure no-op: no DB insert, returns nothing."""
    store = CapturingStore()
    recorder = SessionRecorder(
        store=store, cold_storage=None, ttl_days=30, threshold_bytes=1_048_576
    )
    result = await recorder.record(
        response_id="resp_unstored_xxx",
        original_request={"input": "hi"},
        response_payload={"output": []},
        provider="deepseek",
        model="m",
        session_id=None,
        parent_id=None,
        store_flag=False,
    )
    assert result is None
    assert store.records == []


async def test_recorder_offloads_to_cold_storage_when_over_threshold() -> None:
    store = CapturingStore()
    cold = InMemoryColdStorage()
    # Threshold 100 bytes — easy to exceed
    recorder = SessionRecorder(store=store, cold_storage=cold, ttl_days=30, threshold_bytes=100)
    big_input = {"input": "x" * 200}
    big_output = {"output": [{"type": "message", "content": "y" * 200}]}
    await recorder.record(
        response_id="resp_big_xxx",
        original_request=big_input,
        response_payload=big_output,
        provider="deepseek",
        model="m",
        session_id=None,
        parent_id=None,
        store_flag=True,
    )
    rec = store.records[0]
    assert rec.cold_storage_key is not None
    assert rec.input_json is None
    assert rec.output_json is None
    full = cold.get_sync(rec.cold_storage_key)
    assert full == {"input": big_input, "output": big_output}


async def test_recorder_falls_back_inline_on_cold_write_failure() -> None:
    """If cold storage put() raises, we silently degrade to inline storage instead
    of losing the row. The error is logged but doesn't propagate."""
    store = CapturingStore()

    class ExplodingCold:
        async def put(self, payload: dict[str, Any]) -> str:
            raise RuntimeError("S3 down")

        async def get(self, key: str) -> dict[str, Any]:
            raise RuntimeError("S3 down")

    recorder = SessionRecorder(
        store=store, cold_storage=ExplodingCold(), ttl_days=30, threshold_bytes=1
    )
    await recorder.record(
        response_id="resp_fallback_xxx",
        original_request={"input": "hi"},
        response_payload={"output": []},
        provider="deepseek",
        model="m",
        session_id=None,
        parent_id=None,
        store_flag=True,
    )
    rec = store.records[0]
    assert rec.cold_storage_key is None  # cold path failed
    assert rec.input_json == {"input": "hi"}  # inline fallback succeeded
