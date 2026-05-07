"""Tests for StreamBridge — tee streaming events while building final state."""

from __future__ import annotations

from typing import Any

from gateway.streaming import StreamBridge


def _evt(t: str, **kwargs: Any) -> dict[str, Any]:
    return {"type": t, **kwargs}


async def test_bridge_forwards_all_events_and_builds_final_state() -> None:
    events = [
        _evt("response.created", response={"id": "resp_x", "output": []}),
        _evt("response.output_item.added", item={"type": "message", "id": "msg_1"}),
        _evt("response.content_part.added", part={"type": "output_text"}),
        _evt("response.output_text.delta", delta="Hel"),
        _evt("response.output_text.delta", delta="lo"),
        _evt("response.output_text.done", text="Hello"),
        _evt(
            "response.output_item.done",
            item={
                "type": "message",
                "id": "msg_1",
                "content": [{"type": "output_text", "text": "Hello"}],
            },
        ),
        _evt(
            "response.completed",
            response={
                "id": "resp_x",
                "output": [],
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        ),
    ]

    bridge = StreamBridge()
    forwarded: list[dict[str, Any]] = []

    async def src() -> Any:
        for e in events:
            yield e

    async for evt in bridge.tee(src()):
        forwarded.append(evt)

    assert forwarded == events
    final = bridge.final_state()
    assert final["usage"]["input_tokens"] == 1
    assert any(
        item["content"][0]["text"] == "Hello"
        for item in final["output"]
        if item.get("type") == "message"
    )


async def test_bridge_handles_function_call_arguments_delta() -> None:
    events = [
        _evt("response.created", response={"id": "resp_y", "output": []}),
        _evt(
            "response.output_item.added",
            item={
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "search",
                "arguments": "",
            },
        ),
        _evt("response.function_call_arguments.delta", item_id="fc_1", delta='{"q":"'),
        _evt("response.function_call_arguments.delta", item_id="fc_1", delta='hi"}'),
        _evt("response.function_call_arguments.done", item_id="fc_1", arguments='{"q":"hi"}'),
        _evt(
            "response.output_item.done",
            item={
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "search",
                "arguments": '{"q":"hi"}',
            },
        ),
        _evt("response.completed", response={"id": "resp_y", "output": [], "usage": {}}),
    ]
    bridge = StreamBridge()

    async def src() -> Any:
        for e in events:
            yield e

    async for _ in bridge.tee(src()):
        pass

    final = bridge.final_state()
    fc_items = [it for it in final["output"] if it.get("type") == "function_call"]
    assert len(fc_items) == 1
    assert fc_items[0]["arguments"] == '{"q":"hi"}'


async def test_bridge_rewrites_id_in_lifecycle_events() -> None:
    """When constructed with rewrite_id, lifecycle events' response.id must be replaced."""
    events = [
        {"type": "response.created", "response": {"id": "litellm_orig", "output": [], "usage": {}}},
        {"type": "response.output_text.delta", "delta": "hi"},
        {
            "type": "response.completed",
            "response": {"id": "litellm_orig", "output": [], "usage": {}},
        },
    ]

    async def src() -> Any:
        for e in events:
            yield e

    bridge = StreamBridge(rewrite_id="resp_gateway_xxx")
    forwarded = [evt async for evt in bridge.tee(src())]
    # Lifecycle events rewritten:
    assert forwarded[0]["response"]["id"] == "resp_gateway_xxx"
    assert forwarded[2]["response"]["id"] == "resp_gateway_xxx"
    # Non-lifecycle event (delta) untouched:
    assert "response" not in forwarded[1]
