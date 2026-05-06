# [gap] GET / DELETE / cancel responses endpoints

**Type:** Adaptation gap
**Priority:** P3
**Status:** ⚪ Observe
**Labels:** `type/gap` `priority/P3` `area/state`

## Context

Responses API spec includes:

- `GET /v1/responses/{id}` — retrieve stored response
- `POST /v1/responses/{id}/cancel` — cancel in-progress (paired with background mode)
- `DELETE /v1/responses/{id}` — delete stored response
- `GET /v1/responses/{id}/input_items` — list input items

LiteLLM has `response_polling/` for stream resume but not the full CRUD surface.

## Trigger conditions

- Background mode (#0006) shipped → cancel + status check needed
- Compliance / data-deletion clients need DELETE
- IDE clients want input_items inspection (Cursor, Cline)

## References

- Gap analysis: §4 (CRUD endpoints row)
- LiteLLM existing: `litellm/proxy/response_polling/`
- Related: #0006 (background mode)
- OpenAI spec: https://platform.openai.com/docs/api-reference/responses
