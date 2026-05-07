# Responses Gateway

> OpenAI Responses API gateway for non-OpenAI LLMs. Bridges Cursor / Codex CLI / Cline / ChatGPT Apps SDK clients to Chinese & other non-OpenAI models (Qwen / DeepSeek / Moonshot / GLM / Doubao / MiniMax / ERNIE / Hunyuan ...) via [LiteLLM](https://github.com/BerriAI/litellm).

## Quickstart

### Option A — Docker Compose (gateway + Postgres in one shot)

```bash
cp config.example.yaml config.yaml      # edit to taste
cp models.example.yaml models.yaml      # add your provider api keys
make docker-up                          # builds image + starts postgres + gateway
make docker-logs                        # tail gateway logs
```

Migrations run on container startup; the gateway's `storage.url` is overridden via the `GATEWAY_STORAGE__URL` env var so it always reaches the compose Postgres regardless of what `config.yaml` says. Service is exposed on **`localhost:9090`** (mapped to 8080 inside the container).

### Option B — Host-side dev loop (faster reload)

```bash
uv pip install -e ".[dev,postgres,s3]"

mkdir -p data
docker compose up -d postgres                   # only the DB
GATEWAY_STORAGE__URL=postgresql+asyncpg://gateway:gateway@localhost:5432/gateway_dev \
  uv run alembic upgrade head

cp config.example.yaml config.yaml              # use `localhost` host
cp models.example.yaml models.yaml
make dev                                        # uvicorn --reload on port 8080
```

## Configuration

See [`config.example.yaml`](config.example.yaml). Override any field via `GATEWAY_<SECTION>__<FIELD>` env vars (use `__` between section/field, e.g. `GATEWAY_SERVER__PORT=9000`).

For models, point `litellm.model_list_path` at a [LiteLLM `model_list` YAML](https://docs.litellm.ai/docs/proxy/configs). The gateway uses it purely as an alias map (`{model_name: litellm_string}`); no `litellm.Router` is instantiated.

## Auth

The gateway does not authenticate requests. Run it behind a reverse proxy (Caddy / nginx / oauth2-proxy / Cloudflare Access) that handles auth.

## What works today (v1)

- Full Responses API protocol surface for non-OpenAI models (via LiteLLM SDK)
- `previous_response_id` stateful chains (self-managed in SQLite or Postgres)
  - Walks the `parent_id` chain (not `session_id`) so branched siblings don't bleed in
  - Drops past `instructions` when reconstructing — only the new request's `instructions` is the system prompt
- `store: true / false` honored (`store=false` returns an id but doesn't persist; subsequent retrieval will 404 by design)
- Streaming with proper `response.output_item.added` / `.delta` / `.done` events
  - Gateway response id is rewritten into all lifecycle events from `response.created` onward
- `function_call` tools
- `reasoning` output items (provider-dependent — verify per model)
- `file_search` tool (via LiteLLM emulation; requires LiteLLM vector store config)
- `mcp` tool pass-through

## What's explicitly rejected (with 422)

- `tools[*].type ∈ {web_search, web_search_preview, code_interpreter, computer_use_preview}` — see [issues #2, #4, #5](https://github.com/SimonGino/responses-gateway/issues)
- `background: true` — see issue #6
- `truncation: "auto"` — see issue #8
- `conversation`, `context_management` — newer OpenAI fields not yet bridged

This is deliberate: silent failure is more dangerous than explicit rejection. See [issue #1](https://github.com/SimonGino/responses-gateway/issues/1).

## What's NOT supported in v1

- Cross-provider `previous_response_id` chains (parent.provider != current.provider → 409)
- Background async mode (`background: true`)
- `litellm.Router` features (load balance / fallback chains / cooldown) — punt to upstream LB
- Built-in tool emulation (web_search / code_interpreter / computer_use)

## Architecture

- [Gap analysis](docs/superpowers/specs/2026-05-06-chinese-models-responses-api-gap-analysis-design.md) — what LiteLLM gives us and what it doesn't
- [Architecture spec](docs/superpowers/specs/2026-05-07-gateway-architecture-design.md) — the full design
- [Implementation plan](docs/superpowers/plans/2026-05-07-v1-implementation-plan.md) — task-by-task TDD execution

## Development

```bash
make test           # full suite
make test-unit      # fast
make test-integration  # SQLite + (optionally) Postgres
make lint
make typecheck
make format
```

To run integration tests against Postgres:

```bash
docker compose up -d postgres
GATEWAY_TEST_STORAGE=postgres \
GATEWAY_TEST_POSTGRES_URL=postgresql+asyncpg://gateway:gateway@localhost:5432/gateway_test \
make test-integration
```

To run the smoke test against a real DeepSeek API:

```bash
DEEPSEEK_API_KEY=sk-... uv run pytest tests/e2e/test_smoke_deepseek.py -v -m smoke
```

## License

MIT
