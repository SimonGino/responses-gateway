# [gap] code_interpreter sandbox execution

**Type:** Adaptation gap
**Priority:** P2
**Status:** ⚪ Observe
**Labels:** `type/gap` `priority/P2` `area/tools` `scope/emulation`

## Context

LiteLLM only parses `code_interpreter_call` output items if a provider returns them (`transformation.py:1779-1825`); no sandbox execution layer exists. Chinese models don't natively produce these output items.

## Trigger conditions

- Data-analysis or coding-agent client requests Python execution against a Chinese model

## Sketch

Same pattern as #0002: inject as function tool → intercept call → execute in sandbox (E2B / Daytona / self-hosted Docker) → feed result back → wrap as `code_interpreter_call` output.

## Key open questions (deferred to spec phase)

- Sandbox vendor selection (cost / cold-start / file IO)
- File mounting / persistence between turns within a session
- Resource limits (CPU / memory / wallclock / network egress)
- Output capture format (stdout / stderr / images / files)

## References

- Gap analysis: §4 (`code_interpreter` row)
- LiteLLM current behavior: `transformation.py:1779-1825`
- Reference impl pattern: `litellm/responses/file_search/emulated_handler.py`
- Sandbox options: E2B (https://e2b.dev/), Daytona, Riza, self-hosted Docker

## Out of scope (until promoted)

Full design lives in a future spec when this is promoted to 🟠 Blocking.
