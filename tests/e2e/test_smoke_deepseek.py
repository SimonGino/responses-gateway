"""Smoke test: real call against DeepSeek API. Gated; requires DEEPSEEK_API_KEY."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from gateway.api import build_app
from gateway.config import GatewayConfig
from gateway.session.models import Base
from gateway.session.store import SessionStore

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        not os.getenv("DEEPSEEK_API_KEY"), reason="set DEEPSEEK_API_KEY to run smoke test"
    ),
]


@pytest.fixture
def client() -> Iterator[TestClient]:
    cfg = GatewayConfig()
    cfg.storage.url = "sqlite+aiosqlite:///:memory:"
    app = build_app(cfg)
    store: SessionStore = app.state.session_store
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(store.create_schema(Base.metadata))
    with TestClient(app) as c:
        yield c


def test_real_deepseek_simple_call(client: TestClient) -> None:
    r = client.post(
        "/v1/responses",
        json={
            "input": "Reply with the single word: pong",
            "model": "deepseek/deepseek-chat",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"].startswith("resp_")
    assert "output" in body
    text_items = [
        c["text"]
        for item in body["output"]
        if item.get("type") == "message"
        for c in item.get("content", [])
        if c.get("type") == "output_text"
    ]
    assert text_items
    assert "pong" in "".join(text_items).lower()


def test_real_deepseek_chain_with_previous_response_id(client: TestClient) -> None:
    r1 = client.post(
        "/v1/responses",
        json={
            "input": "Pick a random color and remember it.",
            "model": "deepseek/deepseek-chat",
        },
    )
    assert r1.status_code == 200
    rid_1 = r1.json()["id"]

    r2 = client.post(
        "/v1/responses",
        json={
            "input": "What color did you pick? Reply with just the color.",
            "model": "deepseek/deepseek-chat",
            "previous_response_id": rid_1,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["id"].startswith("resp_")
