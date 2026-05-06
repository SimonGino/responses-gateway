# [gap] truncation: auto input handling

**Type:** Adaptation gap
**Priority:** P2
**Status:** ⚪ Observe
**Labels:** `type/gap` `priority/P2` `area/protocol`

## Context

`transformation.py:1692` only forwards `truncation` from the response object; the input field `truncation: "auto"` has no handler — input messages are passed unchanged regardless of context-window pressure.

## Trigger conditions

- Customer reports `context_length_exceeded` errors with `truncation: "auto"` set
- OR: long-conversation clients (with `previous_response_id`) hit context window limits

## Sketch

- Token-count input messages (use existing `litellm.token_counter`)
- If exceeds model's context window:
  - Drop oldest non-system messages until it fits
  - Preserve `instructions` and last N user/assistant exchanges
  - Optionally summarize dropped messages (separate feature)

## References

- Gap analysis: §4 (`truncation: auto` row)
- LiteLLM behavior: `transformation.py:1692`
- Related: #0001 (until shipped, reject `truncation: "auto"` with explicit error)
