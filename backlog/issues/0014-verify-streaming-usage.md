# [verify] Streaming usage filling on Chinese providers

**Type:** Verification task
**Priority:** P1
**Status:** 🟡 Tracked
**Labels:** `type/verification` `priority/P1` `area/streaming` `area/billing`

## Context

If a provider doesn't return `usage` in the final stream chunk, LiteLLM falls back to local `token_counter()` (`streaming_chunk_builder_utils.py:657-670`). Local count accuracy depends on tokenizer selection — wrong tokenizer = wrong cost + spend tracking.

## Goal

For each Chinese provider, confirm whether streaming returns usage. If local fallback is used, validate tokenizer alignment.

## Targets

(Same provider list as #0012)

## Tasks

- [ ] For each provider: run a streamed request, inspect last chunk for `usage` field
- [ ] If `usage` present: confirm field shape matches LiteLLM expectations
- [ ] If `usage` missing: identify which tokenizer LiteLLM uses for that model
- [ ] Compare local count vs the same prompt's non-streaming `usage` → tolerance ±5%
- [ ] If divergence > 5%: file issue to register correct tokenizer
- [ ] Document matrix in `docs/provider-matrix/streaming-usage.md`

## References

- Gap analysis: §5 item 4
- LiteLLM fallback: `streaming_chunk_builder_utils.py:657-670`
- Tokenizer registry: `litellm/utils.py:2180-2217` (`_select_tokenizer_helper`)
