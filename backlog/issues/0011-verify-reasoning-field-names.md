# [verify] reasoning_content field-name consistency across Chinese reasoning models

**Type:** Verification task
**Priority:** P1
**Status:** 🟡 Tracked
**Labels:** `type/verification` `priority/P1` `area/reasoning`

## Context

LiteLLM's `_extract_reasoning_output_items()` (`transformation.py:1807-1833`) looks for `reasoning_content` in chat completion responses. DeepSeek-R1 uses this exact field name. Other Chinese reasoning models may use different names; if so, LiteLLM silently produces empty `{type: "reasoning"}` output items.

## Goal

Confirm the field name each model uses for chain-of-thought output, document the matrix, and decide whether the gateway needs an alias-mapper layer.

## Tasks

- [ ] **DeepSeek-R1**: confirmed `reasoning_content` (sanity check only)
- [ ] **Qwen QwQ** on DashScope: capture raw response, check field name
- [ ] **Qwen3-Max with `reasoning_effort`**: same
- [ ] **GLM-Zen / GLM-4.6 thinking mode**: capture raw response
- [ ] **Doubao-1.5-thinking**: capture raw response (Volcengine Ark)
- [ ] **Hunyuan-T1**: capture raw response (Tencent Cloud)
- [ ] **MiniMax-M2** (if applicable): capture raw response
- [ ] **Moonshot Kimi-K2-thinking**: capture raw response
- [ ] Document findings in `docs/provider-matrix/reasoning-fields.md`
- [ ] If ≥1 deviation found, file new issue for alias mapper layer

## Method

For each provider:
1. Run a simple completion with reasoning enabled
2. Capture full raw chunk(s) + final response
3. Identify any field containing chain-of-thought content
4. Verify behavior end-to-end with `litellm.responses(...)` — does the `reasoning` output item populate?

## References

- Gap analysis: §5 item 1
- LiteLLM impl: `transformation.py:1807-1833` (`_extract_reasoning_output_items`)
- DeepSeek field reference: https://api-docs.deepseek.com/guides/reasoning_model
