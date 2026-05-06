# [decision] previous_response_id support in SDK-only mode

**Type:** Architecture decision + adaptation gap
**Priority:** P1
**Status:** 🟡 Tracked
**Labels:** `type/decision` `priority/P1` `area/state` `scope/architecture`

## Context

LiteLLM's `previous_response_id` reconstruction (`session_handler.py:31`) reads from `LiteLLM_SpendLogs` (Postgres, populated by **LiteLLM Proxy**) and cold storage. If the gateway uses LiteLLM as **SDK only** (not as Proxy backend), this path doesn't fire — `previous_response_id` becomes silently broken.

This blocks the Q3' architecture decision (Wrap LiteLLM Proxy vs SDK-only vs Fork).

## Decision points

| Option | Effort | Trade-off |
|---|---|---|
| **A1: Wrap LiteLLM Proxy** | Low (use as-is) | Inherit Postgres + Prisma + spend_logs schema; gateway becomes a thin layer |
| **A2: SDK-only + reimplement** | 3-5 days | Own table for response→messages; full control but rebuilds infra |
| **A3: Fork session_handler** | 1-2 days | Vendor LiteLLM's logic, decouple from spend_logs schema; brittle to upstream changes |

## Trigger conditions

- This is the **next brainstorming session** topic — must be decided before implementation begins

## Acceptance criteria (per option)

For **A2** (SDK-only):
- [ ] Schema for response storage (`response_id` → original request, output, model, provider, timestamp, TTL)
- [ ] Drop-in replacement for `ResponsesSessionHandler.get_chat_completion_message_history_for_previous_response_id`
- [ ] Cleanup job for expired responses
- [ ] Cross-provider session continuity (validate: when `previous_response_id` resolves to a different model than current request)
- [ ] Cold-storage offload story for large historical payloads

## References

- Gap analysis: §3 (`previous_response_id` caveat), §4 (SDK-only mode row)
- LiteLLM impl: `litellm/responses/litellm_completion_transformation/session_handler.py`
- Related: #0016 (cross-provider boundary verification)
