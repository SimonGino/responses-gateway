# [gap] web_search emulation for Chinese / non-OpenAI providers

**Type:** Adaptation gap
**Priority:** P0
**Status:** 🟡 Tracked
**Labels:** `type/gap` `priority/P0` `area/tools` `scope/emulation`

## Context

OpenAI Responses API exposes `{"type": "web_search"}` as a **server-executed** built-in tool. LiteLLM translates it to OpenAI's `web_search_options` field (`transformation.py:1371-1384`); Chinese providers ignore that field entirely. Users expecting web search get model hallucinations.

The reference pattern already exists in LiteLLM for `file_search` (`responses/file_search/emulated_handler.py`): inject as a regular function tool, intercept the model's call, run the actual search, wrap the output as a `file_search_call` + `file_citation` annotation. This issue replicates that pattern for `web_search`.

## Trigger conditions

- ≥1 customer/user requests web-search support against a Chinese model
- OR: production logs show non-trivial fraction of requests carry `web_search` tool against unsupported providers (telemetry from #0001)

## Proposed approach

1. Detect `tools: [{type: "web_search" | "web_search_preview"}]` in incoming Responses request
2. Inject as function tool definition (`name: "litellm_web_search"`) into chat/completions request, with `parameters: {query: string, num_results?: integer}`
3. When the model emits the function call, intercept in the gateway loop:
   - Call configured backend (Brave / Tavily / SerpAPI / Bocha — pluggable)
   - Format results as a tool result message
   - Loop back to chat/completions with the result
4. On final assistant message, emit Responses-API output items:
   - `web_search_call` output item with the queries
   - `message` output item with `output_text.annotations: [{type:"url_citation", url, title, start_index, end_index}]`

## Acceptance criteria

- [ ] Pluggable `SearchProvider` protocol (1 method: `async def search(query, num_results) -> List[SearchResult]`)
- [ ] At least 2 implementations: Brave + Tavily
- [ ] `search_context_size: low/medium/high` honored (maps to result count)
- [ ] `user_location` honored where backend supports it
- [ ] Streaming: emit `web_search_call.in_progress` / `.searching` / `.completed` events at appropriate points
- [ ] Tested against ≥3 Chinese providers (DashScope Qwen, DeepSeek, GLM)
- [ ] Configuration: backend selection via env / yaml; API keys via env
- [ ] Failure modes: backend timeout, rate-limit, zero results — each gets explicit handling

## References

- Gap analysis: §4 (`web_search` row)
- LiteLLM reference impl: `litellm/responses/file_search/emulated_handler.py` (entire file is the template)
- LiteLLM web_search current behavior: `transformation.py:1371-1384`
- OpenAI Responses tool spec: https://platform.openai.com/docs/guides/tools-web-search
- Blocked-by: #0001 (rejection layer must report `tool_not_supported` until shipped)
- Blocks: #0009 (`url_citation` annotations need this to populate)

## Out of scope

- Native provider search toggles (#0003) — separate strategy
- Multi-engine fallback within a single request (could be added later)
- Search result caching (separate optimization)
