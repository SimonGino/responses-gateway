# [gap] url_citation annotations in output_text

**Type:** Adaptation gap
**Priority:** P2
**Status:** ⚪ Observe (blocked by #0002)
**Labels:** `type/gap` `priority/P2` `area/output` `scope/blocked`

## Context

Responses API supports `output_text.annotations: [{type: "url_citation", url, title, start_index, end_index}]`. LiteLLM produces `file_citation` (via file_search emulation) but no `url_citation` path exists.

## Trigger conditions

- Search-emulation (#0002) ships → citations need to be surfaced
- Native search (#0003) ships → provider-specific citation formats need normalization
- Clients (Cursor, Claude Code, Codex) start rendering citations from response

## Sketch

Citation extractor that:
1. Tracks tool-result URLs through the agent loop
2. After final answer, fuzzy-matches model output substrings against tool-result content
3. Emits annotations with character offsets in `output_text.text`

## References

- Gap analysis: §4 (`Annotations 完整性` row)
- Blocked-by: #0002, #0003
