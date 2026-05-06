# [v1] Graceful rejection of unsupported Responses API features

**Type:** Cross-cutting feature
**Priority:** P0
**Status:** 🟠 Blocking
**Labels:** `type/feature` `priority/P0` `area/protocol` `scope/rejection`

## Context

LiteLLM today silently ignores several Responses API fields when bridging to non-OpenAI providers (see gap analysis §4):

- `tools: [{type: "web_search"}]` → translated to `web_search_options`, dropped by Chinese providers; request looks normal but no search happens
- `background: true` → ignored, request runs synchronously
- `truncation: "auto"` → ignored, no truncation applied
- `tools: [{type: "code_interpreter"}]` / `[{type: "computer_use_preview"}]` → silently dropped

Silent failure is dangerous: the client thinks the feature was used and trusts model output that's actually fabricated.

## Goal

The gateway must **explicitly reject** any unsupported field with a clear, structured error before forwarding to LiteLLM, so client developers know what's going on.

## Acceptance criteria

- [ ] Validation layer that runs **before** `litellm.responses(...)` is called
- [ ] Rejected fields produce a 400 / 422 response with structured error:
  ```json
  {
    "error": {
      "type": "feature_not_supported",
      "code": "tool_not_supported_for_provider",
      "param": "tools[0].type",
      "message": "<feature> is not yet supported for provider '<provider>'. Track at <issue-link>. Workaround: <hint>."
    }
  }
  ```
- [ ] Per-provider, per-feature support matrix (config or code) — same matrix powers `supports` field in `/v1/models`
- [ ] Coverage:
  - [ ] `tools[*].type` ∈ {`web_search`, `web_search_preview`, `code_interpreter`, `computer_use_preview`} → reject when provider doesn't support it natively
  - [ ] `background: true` → reject
  - [ ] `truncation: "auto"` → reject (or downgrade to `"disabled"` with response header warning)
- [ ] Override header `X-Gateway-Allow-Silent-Fallback: true` for clients explicitly opting into LiteLLM's current silent-drop behavior
- [ ] Tests for each rejection path
- [ ] Per-feature counter / logger so we can quantify demand for #0002, #0004, #0006 etc.

## References

- Gap analysis: `docs/superpowers/specs/2026-05-06-chinese-models-responses-api-gap-analysis-design.md` §4
- LiteLLM silent-fail evidence: `transformation.py:1371-1384` (web_search), grep zero hits for `background_mode`
- OpenAI error format: https://platform.openai.com/docs/guides/error-codes/api-errors

## Out of scope

- Implementing any of the rejected features (each has its own issue: #0002, #0004, #0005, #0006)
- Per-tenant overrides (post-v1)
