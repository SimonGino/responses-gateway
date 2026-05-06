# [verify] response_format / structured-output coverage on Chinese providers

**Type:** Verification task
**Priority:** P2
**Status:** ⚪ Observe
**Labels:** `type/verification` `priority/P2` `area/output`

## Goal

Document which Chinese models support `json_object` and `json_schema` modes, and how LiteLLM's pass-through behaves when not supported (error vs degradation vs silent ignore).

## Targets

- Qwen Max / Plus / Turbo / Qwen3 (DashScope)
- DeepSeek-Chat / DeepSeek-Reasoner
- Moonshot Kimi (v1, k2)
- GLM-4.6 / GLM-4-Air
- Doubao series
- MiniMax-M2
- 文心 ERNIE 4.5 / 5.0

## Tasks

- [ ] For each: send Responses request with `text.format = {type: "json_schema", schema: {...}, strict: true}`
- [ ] Capture provider's behavior (error, ignore, partial)
- [ ] Document support matrix
- [ ] If silent-ignore: file issue to add to #0001 rejection layer

## References

- Gap analysis: §5 item 2
