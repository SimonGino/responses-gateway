"""End-to-end tests for /v1/responses (non-streaming + streaming)."""

from __future__ import annotations

import asyncio
import json as _j
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from gateway.api import build_app
from gateway.config import GatewayConfig
from gateway.session.models import Base
from gateway.session.store import SessionStore


@pytest.fixture
def client() -> Iterator[TestClient]:
    cfg = GatewayConfig()
    cfg.storage.url = "sqlite+aiosqlite:///:memory:"
    app = build_app(cfg)
    store: SessionStore = app.state.session_store
    with TestClient(app) as c:
        # Lifespan has run; now create schema in the same event loop TestClient manages
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(store.create_schema(Base.metadata))
        yield c


def test_create_response_happy_path(client: TestClient) -> None:
    fake_resp = {
        "id": "resp_ignored",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hi!"}]}],
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_resp)):
        r = client.post(
            "/v1/responses",
            json={"input": "hi", "model": "deepseek/deepseek-chat"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["id"].startswith("resp_")
    assert body["id"] != "resp_ignored"  # we override LiteLLM's id with our own
    assert body["output"][0]["content"][0]["text"] == "Hi!"


def test_rejects_web_search_tool(client: TestClient) -> None:
    r = client.post(
        "/v1/responses",
        json={
            "input": "hi",
            "model": "deepseek/deepseek-chat",
            "tools": [{"type": "web_search"}],
        },
    )
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["type"] == "feature_not_supported"


def test_previous_response_id_chain(client: TestClient) -> None:
    fake_resp_1 = {
        "id": "ignored",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "first reply"}]}
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    fake_resp_2 = {
        "id": "ignored",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "second reply"}]}
        ],
        "usage": {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
    }
    with patch(
        "gateway.llm.litellm.aresponses",
        new=AsyncMock(side_effect=[fake_resp_1, fake_resp_2]),
    ) as m:
        r1 = client.post(
            "/v1/responses",
            json={"input": "first", "model": "deepseek/deepseek-chat"},
        )
        assert r1.status_code == 200
        first_id = r1.json()["id"]

        r2 = client.post(
            "/v1/responses",
            json={
                "input": "second",
                "model": "deepseek/deepseek-chat",
                "previous_response_id": first_id,
            },
        )
        assert r2.status_code == 200

    # Second LiteLLM call should have received reconstructed history
    second_call_kwargs = m.await_args_list[1].kwargs
    assert "previous_response_id" not in second_call_kwargs
    second_input = second_call_kwargs["input"]
    assert isinstance(second_input, list)
    # Should contain at least 2 prior messages (user "first", assistant reply) + current "second"
    assert len(second_input) >= 3


def test_404_on_unknown_previous_response_id(client: TestClient) -> None:
    r = client.post(
        "/v1/responses",
        json={
            "input": "x",
            "model": "deepseek/deepseek-chat",
            "previous_response_id": "resp_never_created",
        },
    )
    assert r.status_code == 404
    assert r.json()["error"]["type"] == "previous_response_not_found"


def test_streaming_response_persists_final_state(client: TestClient) -> None:
    events = [
        {"type": "response.created", "response": {"id": "ignored", "output": [], "usage": {}}},
        {"type": "response.output_item.added", "item": {"type": "message", "id": "msg_1"}},
        {"type": "response.content_part.added", "part": {"type": "output_text"}},
        {"type": "response.output_text.delta", "delta": "Hi"},
        {"type": "response.output_text.done", "text": "Hi"},
        {
            "type": "response.output_item.done",
            "item": {
                "type": "message",
                "id": "msg_1",
                "content": [{"type": "output_text", "text": "Hi"}],
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": "ignored",
                "output": [],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
        },
    ]

    async def fake_stream() -> AsyncIterator[dict[str, Any]]:
        for e in events:
            yield e

    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_stream())):
        with client.stream(
            "POST",
            "/v1/responses",
            json={"input": "hi", "model": "deepseek/deepseek-chat", "stream": True},
        ) as r:
            assert r.status_code == 200
            chunks = list(r.iter_lines())
    data_lines = [c for c in chunks if c.startswith("data:")]
    # 7 events + 1 [DONE] = 8 data lines
    assert len(data_lines) >= 7
    # First data line should already have the gateway-assigned id (StreamBridge rewrites)
    first_event = _j.loads(data_lines[0][len("data: ") :])
    assert first_event["type"] == "response.created"
    assert first_event["response"]["id"].startswith("resp_")
    assert first_event["response"]["id"] != "ignored"
