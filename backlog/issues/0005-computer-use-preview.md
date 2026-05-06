# [gap] computer_use_preview support

**Type:** Adaptation gap
**Priority:** P3
**Status:** ⚫ Won't do (research-blocked)
**Labels:** `type/gap` `priority/P3` `area/tools` `scope/research`

## Context

Only handled in LiteLLM's Vertex/Gemini path (`llms/vertex_ai/gemini/...:377`). Chinese models don't emit native computer-use action format. Implementing requires:

- VM + browser orchestration
- Vision model in the loop
- Custom prompt protocol to teach Chinese models to output actions
- Action parser
- Screenshot-action-screenshot loop runtime

This is a **research-stage problem** for non-Anthropic / non-Vertex models. Implementation cost: 1-3 months. Quality unproven on Chinese models.

## Trigger conditions

- Strong customer pull (multi-million-dollar contract)
- OR: A Chinese model ships native computer-use output format we can decode
- OR: A robust open-source agent loop emerges that we can adopt

## References

- Gap analysis: §4 (`computer_use_preview` row)
- LiteLLM Vertex impl: `litellm/llms/vertex_ai/gemini/vertex_and_google_ai_studio_gemini.py:377-411`
- Anthropic Computer Use: https://docs.anthropic.com/en/docs/build-with-claude/computer-use
- OpenAI Computer Use: https://platform.openai.com/docs/guides/tools-computer-use
