# [gap] background: true async mode

**Type:** Adaptation gap
**Priority:** P2
**Status:** ⚪ Observe
**Labels:** `type/gap` `priority/P2` `area/state` `scope/runtime`

## Context

LiteLLM has zero handling for `background: true` (`grep -r 'background' litellm/responses/` returns no implementation). Implementing requires an async task runtime + result polling endpoints.

## Trigger conditions

- Long-running task clients (deep research / multi-step agents) need background execution
- OR: clients hit gateway timeout and need fire-and-forget mode

## Sketch

- Job queue (asyncio task pool / Celery / RQ)
- Job state persisted (Postgres or extend `LiteLLM_SpendLogs`)
- `GET /v1/responses/{id}` returns `status: in_progress | completed | failed`
- `POST /v1/responses/{id}/cancel` (paired with #0010)
- SSE polling endpoint for live event subscription on a background response

## References

- Gap analysis: §4 (`后台模式` row), §5 item 5 (rejection behavior to verify)
- Related: #0010 (full CRUD endpoint surface)
