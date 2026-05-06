# Responses Gateway — Adaptation Backlog

> Living TODO. Distinct from the [gap analysis](docs/superpowers/specs/2026-05-06-chinese-models-responses-api-gap-analysis-design.md), which is a frozen snapshot of *what we found*. This file tracks *what we plan to do about it*.

## Status legend

| Status | Meaning |
|---|---|
| ⚫ Won't do | Out of scope for this project (yet) |
| ⚪ Observe | Recorded; no demand, no plan |
| 🟡 Tracked | Acknowledged need; awaiting trigger or capacity |
| 🟠 Blocking | Active demand; promote to in-spec next |
| 🔵 In spec | Implementation spec being written |
| 🟢 In progress | Active development |
| ✅ Done | Shipped (move to CHANGELOG, remove from this table) |

## v1 must-have (cross-cutting)

| # | Issue | Status | Priority |
|---|---|---|---|
| 0001 | [Graceful rejection of unsupported features](backlog/issues/0001-graceful-rejection-for-unsupported-tools.md) | 🟠 Blocking | P0 |

## Adaptation gaps (from gap analysis §4)

| # | Issue | Status | Priority | Trigger |
|---|---|---|---|---|
| 0002 | [`web_search` emulation](backlog/issues/0002-web-search-emulation.md) | 🟡 Tracked | P0 | Codex/Cursor users; observed silent-fail risk |
| 0003 | [Native provider search toggles](backlog/issues/0003-native-search-toggles.md) | 🟡 Tracked | P1 | Quality demand vs emulation |
| 0007 | [`previous_response_id` in SDK-only mode](backlog/issues/0007-previous-response-id-sdk-only.md) | 🟡 Tracked | P1 | Architecture decision (next brainstorm) |
| 0006 | [`background: true` async mode](backlog/issues/0006-background-mode.md) | ⚪ Observe | P2 | Long-running task clients |
| 0008 | [`truncation: auto`](backlog/issues/0008-truncation-auto.md) | ⚪ Observe | P2 | Input-overflow scenarios |
| 0004 | [`code_interpreter` sandbox](backlog/issues/0004-code-interpreter-sandbox.md) | ⚪ Observe | P2 | Data-analysis / coding-agent demand |
| 0009 | [`url_citation` annotations](backlog/issues/0009-url-citation-annotations.md) | ⚪ Observe | P2 | Blocked by 0002 |
| 0010 | [GET / DELETE / cancel endpoints](backlog/issues/0010-responses-crud-endpoints.md) | ⚪ Observe | P3 | Background / state-aware clients |
| 0005 | [`computer_use_preview`](backlog/issues/0005-computer-use-preview.md) | ⚫ Won't do (research-blocked) | P3 | Model capability not yet there |

## Verification tasks (from gap analysis §5)

| # | Issue | Status | Priority |
|---|---|---|---|
| 0011 | [Verify `reasoning_content` field-name consistency](backlog/issues/0011-verify-reasoning-field-names.md) | 🟡 Tracked | P1 |
| 0014 | [Verify streaming usage filling](backlog/issues/0014-verify-streaming-usage.md) | 🟡 Tracked | P1 |
| 0016 | [Verify `previous_response_id` cross-provider boundaries](backlog/issues/0016-verify-previous-response-id-boundaries.md) | 🟡 Tracked | P1 |
| 0012 | [Verify structured-output coverage](backlog/issues/0012-verify-structured-output-coverage.md) | ⚪ Observe | P2 |
| 0013 | [Verify vision input compatibility](backlog/issues/0013-verify-vision-input-compat.md) | ⚪ Observe | P2 |
| 0015 | [Verify MCP tool pass-through](backlog/issues/0015-verify-mcp-passthrough.md) | ⚪ Observe | P2 |

## Workflow

1. **New gap surfaces** → create new issue file under `backlog/issues/NNNN-slug.md`, status ⚪ Observe
2. **Demand grows** → 🟡 Tracked
3. **Blocking real users** → 🟠 Blocking → schedule a brainstorm to produce an impl spec
4. **Spec written** → 🔵 In spec, link to spec file
5. **Implementation starts** → 🟢 In progress
6. **Shipped** → move entry to CHANGELOG, remove from this table

## Migration to GitHub

When the GitHub repo is set up, run:

```bash
./backlog/migrate-to-github.sh
```

Details in [`backlog/README.md`](backlog/README.md).
