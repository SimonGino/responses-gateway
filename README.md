# Responses Gateway (planning)

> **Stage:** Design / planning. No code yet.
> Goal: a lightweight OpenAI Responses API gateway that lets clients (Cursor, Codex CLI, Cline, ChatGPT Apps SDK, ...) talk to **Chinese / non-OpenAI LLMs** (Qwen / DeepSeek / Moonshot / GLM / Doubao / MiniMax / ERNIE / Hunyuan ...) via the same `/v1/responses` protocol.

## Why

OpenAI's Responses API is becoming the de-facto client protocol for next-gen LLM tooling, but most non-OpenAI providers only speak Chat Completions. [LiteLLM](https://github.com/BerriAI/litellm) bridges much of this transparently — but not all of it. This project fills the gap.

## What's here

| Path | What it is |
|---|---|
| [`docs/superpowers/specs/2026-05-06-...-design.md`](docs/superpowers/specs/2026-05-06-chinese-models-responses-api-gap-analysis-design.md) | **Gap analysis** — protocol diff, what LiteLLM handles cleanly, what it doesn't |
| [`BACKLOG.md`](BACKLOG.md) | Living TODO with status / priority / trigger conditions |
| [`backlog/issues/`](backlog/issues/) | One file per backlog item, GitHub-issue-ready |
| [`backlog/migrate-to-github.sh`](backlog/migrate-to-github.sh) | One-shot migration script (`gh issue create -F file.md`) |
| [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) | Templates for future contributors (gap / verification / bug) |

## Status

- ✅ Protocol gap analysis written
- ✅ Backlog seeded with 16 items (9 adaptation gaps + 6 verification tasks + 1 cross-cutting must-have)
- ⏭️ Next: architecture decision (Wrap LiteLLM Proxy / SDK-only / Fork) — see [`#0007`](backlog/issues/0007-previous-response-id-sdk-only.md)
- ⏭️ Then: v1 implementation spec covering the cleanly-bridgeable subset + `#0001` graceful rejection

## Reading order

1. **Start here** → [`BACKLOG.md`](BACKLOG.md)
2. For full context → [gap analysis](docs/superpowers/specs/2026-05-06-chinese-models-responses-api-gap-analysis-design.md)
3. For specific issues → drill into [`backlog/issues/`](backlog/issues/)

## License

To be decided. For now, treat content as "all rights reserved" pending an explicit license.
