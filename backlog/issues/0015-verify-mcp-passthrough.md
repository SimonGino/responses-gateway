# [verify] MCP tool pass-through on Chinese providers

**Type:** Verification task
**Priority:** P2
**Status:** ⚪ Observe
**Labels:** `type/verification` `priority/P2` `area/tools` `area/mcp`

## Context

LiteLLM passes `{"type": "mcp"}` tools through to chat tools (`transformation.py:1368`). Whether Chinese providers recognize this is unverified.

## Goal

For each provider: does sending an MCP tool work, error, or silently no-op?

## Tasks

- [ ] Send MCP tool definition to each Chinese provider
- [ ] Capture response: error / silent-drop / actual MCP execution
- [ ] If silent-drop: file new issue for downgrade-to-function-tool fallback
- [ ] If error: add to #0001 rejection layer with provider-specific message
- [ ] Document support matrix

## References

- Gap analysis: §5 item 6
- LiteLLM impl: `transformation.py:1368` (`if tool.get("type") == "mcp": chat_completion_tools.append(...)`)
- OpenAI MCP tool spec: https://platform.openai.com/docs/guides/tools-remote-mcp
