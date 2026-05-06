# [verify] previous_response_id boundaries (cross-provider, context window, retention)

**Type:** Verification task
**Priority:** P1
**Status:** 🟡 Tracked
**Labels:** `type/verification` `priority/P1` `area/state`

## Goal

Validate edge cases of `previous_response_id` when running through the LiteLLM Proxy + Postgres path, before relying on it in production.

## Tasks

- [ ] **Cross-provider**: `previous_response_id` from request to provider A, follow-up routes to provider B → does session reconstruct correctly? Are tool-call IDs translated?
- [ ] **Cross-model**: same provider, different model with smaller context → behavior on overflow?
- [ ] **Context overflow**: history exceeds new model's window → does LiteLLM truncate, error, or silently send truncated?
- [ ] **Tool call continuity**: tool calls from previous response, current request omits the tool → behavior?
- [ ] **Retention**: how long does `LiteLLM_SpendLogs` retain rows? Default index strategy on `response_id` lookup performance?
- [ ] **Cleanup**: who deletes old rows? Does LiteLLM ship a job?
- [ ] **Cold storage offload**: at what payload size does LiteLLM fall back to cold storage? What happens if cold storage is unavailable?

## References

- Gap analysis: §5 item 7
- LiteLLM impl: `litellm/responses/litellm_completion_transformation/session_handler.py`
- Related: #0007 (architecture decision)
