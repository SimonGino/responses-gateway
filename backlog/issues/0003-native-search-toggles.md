# [gap] Native search toggle for each Chinese provider

**Type:** Adaptation gap
**Priority:** P1
**Status:** 🟡 Tracked
**Labels:** `type/gap` `priority/P1` `area/tools` `area/providers` `scope/passthrough`

## Context

Each Chinese provider has its own way to enable native web search; none match OpenAI's `web_search_options`. LiteLLM has not wired any of them up.

| Provider | Native toggle |
|---|---|
| Qwen DashScope | `extra_body: {enable_search: true, search_options: {forced_search, enable_citation}}` |
| 智谱 GLM | `tools: [{type: "web_search", web_search: {enable: true}}]` (their own schema) |
| Moonshot Kimi | `tools: [{type: "builtin_function", function: {name: "$web_search"}}]` + half-managed callback dance |
| 豆包 Doubao | Application entry on Volcengine Ark, or preset `web_search` tool |
| MiniMax | `tools: [{type: "web_search"}]` (their own format) |
| 文心 ERNIE | `tools: [{type: "search"}]` or `disable_search: false` (version-dependent) |
| DeepSeek | No native search — must fall through to #0002 (emulation) |

## Trigger conditions

- After #0002 ships, customers report quality gap between emulated search and provider-native search
- OR: integration with provider-native citation features needed (e.g. Qwen's citation indexes, GLM's url metadata)

## Proposed approach

When the gateway sees `{"type": "web_search"}`:

1. If the routed provider has a native toggle → translate to that provider's format (passthrough mode)
2. Else → fall through to #0002 emulation
3. Configurable per-provider preference: `prefer: native | emulation | auto`

## Acceptance criteria

- [ ] Per-provider translator functions (one per supported native toggle)
- [ ] Translation tests with recorded fixtures
- [ ] Output normalization: provider-native citation format → Responses `url_citation` annotation (consistent shape across providers)
- [ ] Configuration: `provider.web_search_mode = native | emulation | auto` (auto = native if available, else emulation)
- [ ] Tests against at least DashScope, GLM, Moonshot

## References

- Gap analysis: §4 (`各家原生搜索开关` row)
- Blocked-by: #0001 (rejection layer first), #0002 (emulation as fallback)
- DashScope docs: https://help.aliyun.com/zh/model-studio/qwen-models#search
- Moonshot $web_search: https://platform.moonshot.cn/docs/guide/agent-support
- 智谱 web_search: https://open.bigmodel.cn/dev/api#tools-search

## Out of scope

- Citation format unification across providers (handled in #0009)
- DeepSeek (no native; pure emulation case via #0002)
