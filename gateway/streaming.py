"""Streaming bridge: tee Responses-API events while accumulating the final state.

When constructed with a `rewrite_id`, mutates the `response.id` field of
lifecycle events (response.created / response.in_progress / response.completed /
response.failed / response.incomplete) so the client sees the gateway-assigned
id from the very first event. This guarantees the client can immediately use
that id for a follow-up `previous_response_id` call.

The final state mirrors what a non-streaming response would have looked like, so
SessionRecorder can persist it consistently regardless of streaming mode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

_LIFECYCLE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "response.created",
        "response.in_progress",
        "response.completed",
        "response.failed",
        "response.incomplete",
    }
)

# Per-item events that imply a message item — if we see one before its
# `response.output_item.added`, synthesize the missing announcement.
_MESSAGE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "response.output_text.delta",
        "response.output_text.done",
        "response.refusal.delta",
        "response.refusal.done",
        "response.content_part.added",
        "response.content_part.done",
    }
)
# Subset where a content_part.added is also expected before the event.
_TEXT_PART_EVENT_TYPES: frozenset[str] = frozenset(
    {"response.output_text.delta", "response.output_text.done"}
)


class StreamBridge:
    def __init__(self, *, rewrite_id: str | None = None) -> None:
        self._rewrite_id = rewrite_id
        self._items_by_id: dict[str, dict[str, Any]] = {}
        self._item_order: list[str] = []
        self._final_response: dict[str, Any] = {"output": [], "usage": {}}
        self._announced_items: set[str] = set()
        self._announced_parts: set[tuple[str, int]] = set()

    async def tee(self, source: AsyncIterator[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        """Forward each event downstream while updating the internal final-state buffer.

        Lifecycle events get their `response.id` rewritten to `self._rewrite_id`
        before being forwarded (and before being consumed into final state).

        Defensive normalization: some upstream providers (observed: GLM via
        LiteLLM) start `response.output_text.delta` without first emitting
        `response.output_item.added` / `response.content_part.added`. Strict
        clients (e.g. Cherry Studio) reject the stream with `text part <id> not
        found`. We synthesize the missing announcements so the protocol surface
        stays well-formed.
        """
        async for event in source:
            self._maybe_rewrite_id(event)
            for synthetic in self._synthesize_missing_announcements(event):
                self._consume(synthetic)
                yield synthetic
            self._consume(event)
            yield event

    def _synthesize_missing_announcements(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        etype = event.get("type")
        if etype == "response.output_item.added":
            iid = event.get("item", {}).get("id")
            if iid:
                self._announced_items.add(iid)
            return []
        if etype == "response.content_part.added":
            iid = event.get("item_id")
            if iid:
                cidx = int(event.get("content_index", 0))
                self._announced_parts.add((iid, cidx))
            # Fall through: if the provider sent content_part.added without
            # first sending output_item.added for the parent, the parent
            # synthesis below still needs to fire.
        elif etype not in _MESSAGE_EVENT_TYPES:
            return []
        item_id = event.get("item_id")
        if not isinstance(item_id, str):
            return []
        synth: list[dict[str, Any]] = []
        output_index = event.get("output_index", 0)
        if item_id not in self._announced_items:
            synth.append(
                {
                    "type": "response.output_item.added",
                    "output_index": output_index,
                    "item": {
                        "id": item_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "in_progress",
                        "content": [],
                    },
                }
            )
            self._announced_items.add(item_id)
        if etype in _TEXT_PART_EVENT_TYPES:
            cidx = int(event.get("content_index", 0))
            key = (item_id, cidx)
            if key not in self._announced_parts:
                synth.append(
                    {
                        "type": "response.content_part.added",
                        "item_id": item_id,
                        "output_index": output_index,
                        "content_index": cidx,
                        "part": {
                            "type": "output_text",
                            "text": "",
                            "annotations": [],
                        },
                    }
                )
                self._announced_parts.add(key)
        return synth

    def _maybe_rewrite_id(self, event: dict[str, Any]) -> None:
        if not self._rewrite_id:
            return
        if event.get("type") in _LIFECYCLE_EVENT_TYPES:
            resp = event.get("response")
            if isinstance(resp, dict):
                resp["id"] = self._rewrite_id

    def _consume(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "response.created":
            resp = event.get("response", {})
            self._final_response.update(resp)
            self._final_response.setdefault("output", [])
            self._final_response.setdefault("usage", {})
            return
        if etype == "response.output_item.added":
            item = event.get("item", {})
            iid = item.get("id")
            if iid:
                self._items_by_id[iid] = dict(item)
                self._item_order.append(iid)
            return
        if etype == "response.output_text.delta":
            item = self._latest_item_of_type("message")
            if item:
                content = item.setdefault("content", [])
                if not content or content[-1].get("type") != "output_text":
                    content.append({"type": "output_text", "text": ""})
                content[-1]["text"] += event.get("delta", "")
            return
        if etype == "response.function_call_arguments.delta":
            iid = event.get("item_id")
            if iid and iid in self._items_by_id:
                self._items_by_id[iid]["arguments"] = self._items_by_id[iid].get(
                    "arguments", ""
                ) + event.get("delta", "")
            return
        if etype == "response.output_item.done":
            item = event.get("item", {})
            iid = item.get("id")
            if iid:
                self._items_by_id[iid] = dict(item)
            return
        if etype == "response.completed":
            resp = event.get("response", {})
            usage = resp.get("usage")
            if usage:
                self._final_response["usage"] = usage
            return

    def _latest_item_of_type(self, item_type: str) -> dict[str, Any] | None:
        for iid in reversed(self._item_order):
            item = self._items_by_id.get(iid)
            if item and item.get("type") == item_type:
                return item
        return None

    def final_state(self) -> dict[str, Any]:
        out = dict(self._final_response)
        out["output"] = [self._items_by_id[iid] for iid in self._item_order]
        return out
