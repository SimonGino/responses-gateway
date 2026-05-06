# Responses Gateway v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build v1 of the OpenAI Responses API gateway that routes to non-OpenAI LLMs via LiteLLM SDK, with self-managed `previous_response_id` session storage and explicit rejection of features that LiteLLM cannot bridge.

**Architecture:** FastAPI service. Only LLM dependency is `litellm` SDK (no LiteLLM Proxy). Sessions stored via SQLAlchemy 2.x async with SQLite default and Postgres upgrade path. `previous_response_id` resolved before calling LiteLLM (Intercept-and-Translate pattern). Auth deferred to upstream reverse proxy. See [`spec`](../specs/2026-05-07-gateway-architecture-design.md) and [`gap analysis`](../specs/2026-05-06-chinese-models-responses-api-gap-analysis-design.md).

**Tech Stack:** Python 3.11+, FastAPI, LiteLLM SDK, SQLAlchemy 2.x async, Alembic, Pydantic v2 / pydantic-settings, structlog, pytest + pytest-asyncio, httpx (test client), uvicorn. Optional extras: asyncpg (Postgres), aioboto3 (S3).

---

## File Structure

```
responses-gateway/
├── pyproject.toml
├── Makefile
├── README.md                       (already exists; will update at end)
├── BACKLOG.md                      (already exists)
├── config.example.yaml             (NEW)
├── models.example.yaml             (NEW)
├── docker-compose.yml              (NEW; local Postgres for dev/test)
├── alembic.ini                     (NEW)
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── <hash>_initial_sessions_table.py
├── gateway/
│   ├── __init__.py
│   ├── api.py                      # FastAPI app + routes
│   ├── config.py                   # Pydantic Settings + YAML loader
│   ├── logging_setup.py            # structlog config
│   ├── ids.py                      # uuid7 + response_id helpers
│   ├── errors.py                   # Error types + FastAPI handlers
│   ├── validator.py                # Reject layer (issue #1)
│   ├── llm.py                      # litellm.aresponses wrapper
│   ├── streaming.py                # Stream tee + builder
│   ├── session/
│   │   ├── __init__.py
│   │   ├── models.py               # SQLAlchemy ORM model
│   │   ├── store.py                # SessionStore (async CRUD)
│   │   ├── resolver.py             # SessionResolver (intercept-translate)
│   │   └── recorder.py             # SessionRecorder (post-call persist)
│   └── storage/
│       ├── __init__.py
│       └── cold.py                 # ColdStorage interface + S3 + in-memory
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # shared fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_config.py
│   │   ├── test_ids.py
│   │   ├── test_errors.py
│   │   ├── test_validator.py
│   │   ├── test_session_resolver.py
│   │   ├── test_session_recorder.py
│   │   ├── test_streaming.py
│   │   └── test_cold_storage_inmem.py
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_session_store_sqlite.py
│   │   └── test_session_store_postgres.py
│   └── e2e/
│       ├── __init__.py
│       ├── test_responses_api.py
│       └── test_smoke_deepseek.py  # gated (requires DEEPSEEK_API_KEY)
└── .github/
    ├── ISSUE_TEMPLATE/             (already exists)
    └── workflows/
        └── ci.yml                  (NEW)
```

---

## Task Dependency Graph

```
        ┌──────────────────────────────┐
   1 → 2,3,4,5,7                       │   (3,4,5,7 parallel after 1)
        │                              │
   3 → 8                               │   config → validator
   5 → 6                               │   models → store
   6,7 → 9,10                          │   store + cold → resolver, recorder
   3 → 11                              │   config → llm router
   (none) → 12                         │   stream bridge
   8,9,10,11,12 → 13                   │   FastAPI assembly
   13 → 14 → 15                        │   non-stream → stream → routes done
   13 → 16,17                          │   docker-compose + smoke (parallel)
   all → 18                            │   docs + polish
        └──────────────────────────────┘
```

| Task | Depends on | Spec ref | Issue |
|---|---|---|---|
| 1 Bootstrap | — | §3 | — |
| 2 CI | 1 | §8 | — |
| 3 Config | 1 | §6 | — |
| 4 Logging + IDs + Errors | 1 | §7 | — |
| 5 DB models + Alembic | 1 | §5 | #7 |
| 6 SessionStore | 5 | §5 | #7 |
| 7 ColdStorage | 1 | §5 | — |
| 8 Validator | 3 | §6, §7 | #1 |
| 9 SessionResolver | 6, 7 | §4.1 | #7, #16 |
| 10 SessionRecorder | 6, 7 | §4.1 | #7 |
| 11 LLMRouter | 3 | §3 | — |
| 12 StreamBridge | — | §4.2 | #14 |
| 13 FastAPI skeleton | 4, 8, 9, 10, 11, 12 | §3 | — |
| 14 /v1/responses non-stream | 13 | §4.1 | #1, #7 |
| 15 /v1/responses streaming | 14 | §4.2 | #14 |
| 16 docker-compose | 1 | §8 | — |
| 17 Smoke test | 14, 15 | §8 | #11 |
| 18 README + polish | all | — | — |

---

## Tasks

### Task 1: Project bootstrap

**Spec ref:** §3 Components, §6 Configuration
**Depends on:** —
**Files:**
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `gateway/__init__.py`
- Create: `gateway/session/__init__.py`
- Create: `gateway/storage/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/e2e/__init__.py`
- Create: `tests/conftest.py`
- Modify: `.gitignore` (add Python entries already present, add `data/`)

- [ ] **Step 1.1: Create `pyproject.toml`**

```toml
[project]
name = "responses-gateway"
version = "0.1.0"
description = "OpenAI Responses API gateway for non-OpenAI LLMs"
requires-python = ">=3.11"
authors = [{ name = "SimonGino" }]
readme = "README.md"
license = { text = "MIT" }

dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "litellm>=1.55",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "alembic>=1.14",
    "structlog>=24.4",
    "uuid7>=0.1",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

[project.optional-dependencies]
postgres = ["asyncpg>=0.30"]
s3 = ["aioboto3>=13.2"]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "ruff>=0.7",
    "mypy>=1.13",
    "respx>=0.21",
]

[project.scripts]
responses-gateway = "gateway.api:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["gateway"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
filterwarnings = ["error::DeprecationWarning"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "B", "UP", "W", "ASYNC"]

[tool.mypy]
python_version = "3.11"
strict = true
plugins = ["pydantic.mypy"]
```

- [ ] **Step 1.2: Create `Makefile`**

```makefile
.PHONY: install test test-unit test-integration test-e2e lint format typecheck migrate dev clean

install:
	uv pip install -e ".[dev,postgres,s3]"

test:
	pytest tests/ -v --cov=gateway --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-e2e:
	pytest tests/e2e/ -v -m "not smoke"

lint:
	ruff check gateway/ tests/

format:
	ruff format gateway/ tests/
	ruff check --fix gateway/ tests/

typecheck:
	mypy gateway/

migrate:
	alembic upgrade head

dev:
	uvicorn gateway.api:app --reload --host 0.0.0.0 --port 8080

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
```

- [ ] **Step 1.3: Create empty package files**

```bash
mkdir -p gateway/session gateway/storage tests/unit tests/integration tests/e2e
touch gateway/__init__.py gateway/session/__init__.py gateway/storage/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/e2e/__init__.py
```

- [ ] **Step 1.4: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
from __future__ import annotations
```

- [ ] **Step 1.5: Update `.gitignore`** (append; existing entries already cover .venv, __pycache__)

```
data/
*.db
*.db-journal
.coverage
htmlcov/
.alembic_version
```

- [ ] **Step 1.6: Verify install + sanity check**

```bash
uv pip install -e ".[dev]"
python -c "import gateway; import fastapi; import litellm; import sqlalchemy; print('ok')"
pytest tests/ -v
```

Expected: `ok` printed; pytest collects 0 tests (no tests yet) and exits 5 (no tests run, not an error in this CI policy — accept).

- [ ] **Step 1.7: Commit**

```bash
git add pyproject.toml Makefile gateway/ tests/ .gitignore
git commit -m "feat: project bootstrap with pyproject, Makefile, package skeleton"
```

---

### Task 2: CI workflow

**Spec ref:** §8 Testing
**Depends on:** Task 1
**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 2.1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint-typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv pip install --system -e ".[dev]"
      - run: ruff check gateway/ tests/
      - run: ruff format --check gateway/ tests/
      - run: mypy gateway/

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
        storage: [sqlite, postgres]
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: gateway
          POSTGRES_PASSWORD: gateway
          POSTGRES_DB: gateway_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install --system -e ".[dev,postgres]"
      - name: Run unit + integration tests
        env:
          GATEWAY_TEST_STORAGE: ${{ matrix.storage }}
          GATEWAY_TEST_POSTGRES_URL: postgresql+asyncpg://gateway:gateway@localhost:5432/gateway_test
        run: pytest tests/unit/ tests/integration/ -v --cov=gateway --cov-report=xml
      - uses: codecov/codecov-action@v4
        if: matrix.python-version == '3.12' && matrix.storage == 'postgres'
        with:
          files: ./coverage.xml
```

- [ ] **Step 2.2: Verify YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no output (no exception).

- [ ] **Step 2.3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint + typecheck + matrix test workflow"
```

---

### Task 3: Configuration layer

**Spec ref:** §6 Configuration
**Depends on:** Task 1
**Files:**
- Create: `gateway/config.py`
- Create: `tests/unit/test_config.py`
- Create: `config.example.yaml`

- [ ] **Step 3.1: Write failing test `tests/unit/test_config.py`**

```python
"""Tests for gateway configuration loading."""
from __future__ import annotations

from pathlib import Path

import pytest

from gateway.config import GatewayConfig, load_config


def test_load_config_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        """
storage:
  url: "sqlite+aiosqlite:///./data/sessions.db"
  cold:
    enabled: false
    threshold_bytes: 1048576
litellm:
  model_list_path: ./models.yaml
  request_timeout: 60
session:
  default_ttl_days: 30
  default_store: true
reject:
  tools: ["web_search", "code_interpreter"]
  fields:
    background: true
server:
  host: "0.0.0.0"
  port: 8080
  log_level: "info"
  log_format: "json"
  trust_proxy_headers: true
"""
    )
    cfg = load_config(yaml_path)
    assert isinstance(cfg, GatewayConfig)
    assert cfg.storage.url.startswith("sqlite+aiosqlite")
    assert cfg.session.default_ttl_days == 30
    assert "web_search" in cfg.reject.tools
    assert cfg.server.port == 8080


def test_env_override_takes_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("server:\n  port: 8080\n")
    monkeypatch.setenv("GATEWAY_SERVER__PORT", "9999")
    cfg = load_config(yaml_path)
    assert cfg.server.port == 9999


def test_missing_yaml_uses_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    cfg = load_config(missing)
    assert cfg.server.port == 8080  # default
```

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway.config'`.

- [ ] **Step 3.2: Implement `gateway/config.py`**

```python
"""Gateway configuration. YAML file + GATEWAY_ env override."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ColdStorageConfig(BaseModel):
    enabled: bool = False
    backend: str = "s3"  # s3 | gcs | inmem
    bucket_url: str | None = None
    threshold_bytes: int = 1_048_576  # 1 MiB


class StorageConfig(BaseModel):
    url: str = "sqlite+aiosqlite:///./data/sessions.db"
    cold: ColdStorageConfig = Field(default_factory=ColdStorageConfig)


class LiteLLMConfig(BaseModel):
    model_list_path: str | None = None
    request_timeout: int = 60
    num_retries: int = 2


class SessionConfig(BaseModel):
    default_ttl_days: int = 30
    default_store: bool = True


class RejectConfig(BaseModel):
    tools: list[str] = Field(
        default_factory=lambda: [
            "web_search",
            "web_search_preview",
            "code_interpreter",
            "computer_use_preview",
        ]
    )
    fields: dict[str, Any] = Field(default_factory=lambda: {"background": True, "truncation": "auto"})
    workaround_url_template: str = (
        "https://github.com/SimonGino/responses-gateway/issues?q=is%3Aissue+{feature}"
    )


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"
    log_format: str = "json"
    trust_proxy_headers: bool = True


class GatewayConfig(BaseSettings):
    """Top-level config. Env vars override YAML with `GATEWAY_<SECTION>__<FIELD>`."""

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    storage: StorageConfig = Field(default_factory=StorageConfig)
    litellm: LiteLLMConfig = Field(default_factory=LiteLLMConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    reject: RejectConfig = Field(default_factory=RejectConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def load_config(path: Path | str) -> GatewayConfig:
    """Load YAML config, then layer env overrides on top."""
    yaml_data: dict[str, Any] = {}
    p = Path(path)
    if p.exists():
        with p.open() as f:
            yaml_data = yaml.safe_load(f) or {}
    return GatewayConfig(**yaml_data)
```

- [ ] **Step 3.3: Create `config.example.yaml`** (matches spec §6 verbatim — reference for users)

```yaml
storage:
  url: "sqlite+aiosqlite:///./data/sessions.db"
  cold:
    enabled: false
    backend: "s3"
    bucket_url: "s3://my-bucket/sessions"
    threshold_bytes: 1048576

litellm:
  model_list_path: ./models.yaml
  request_timeout: 60
  num_retries: 2

session:
  default_ttl_days: 30
  default_store: true

reject:
  tools:
    - web_search
    - web_search_preview
    - code_interpreter
    - computer_use_preview
  fields:
    background: true
    truncation: "auto"
  workaround_url_template: "https://github.com/SimonGino/responses-gateway/issues?q=is%3Aissue+{feature}"

server:
  host: "0.0.0.0"
  port: 8080
  log_level: info
  log_format: json
  trust_proxy_headers: true
```

- [ ] **Step 3.4: Run tests pass**

Run: `pytest tests/unit/test_config.py -v`
Expected: 3 PASSED.

- [ ] **Step 3.5: Commit**

```bash
git add gateway/config.py tests/unit/test_config.py config.example.yaml
git commit -m "feat(config): YAML + env config with Pydantic Settings"
```

---

### Task 4: Logging, IDs, error types

**Spec ref:** §7 Error Handling
**Depends on:** Task 1
**Files:**
- Create: `gateway/ids.py`
- Create: `gateway/errors.py`
- Create: `gateway/logging_setup.py`
- Create: `tests/unit/test_ids.py`
- Create: `tests/unit/test_errors.py`

- [ ] **Step 4.1: Write failing test `tests/unit/test_ids.py`**

```python
"""Tests for ID generation helpers."""
from __future__ import annotations

from gateway.ids import new_request_id, new_response_id, new_session_id


def test_response_id_has_resp_prefix() -> None:
    rid = new_response_id()
    assert rid.startswith("resp_")
    assert len(rid) > 30


def test_session_id_is_uuid_string() -> None:
    sid = new_session_id()
    assert isinstance(sid, str)
    assert len(sid) >= 32


def test_ids_are_unique() -> None:
    ids = {new_response_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_request_id_format() -> None:
    rid = new_request_id()
    assert isinstance(rid, str)
    assert len(rid) >= 32
```

Run: `pytest tests/unit/test_ids.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 4.2: Implement `gateway/ids.py`**

```python
"""ID generators using uuid7 (time-sortable)."""
from __future__ import annotations

from uuid_extensions import uuid7str  # provided by `uuid7` package


def new_response_id() -> str:
    """Generate a new Responses API id (`resp_<uuid7>`)."""
    return f"resp_{uuid7str()}"


def new_session_id() -> str:
    """Generate a new session/thread id (raw uuid7 string)."""
    return uuid7str()


def new_request_id() -> str:
    """Generate a new HTTP-level request correlation id."""
    return uuid7str()
```

Note: `uuid_extensions` is from the `uuid7` PyPI package. If unavailable, fall back to `uuid.uuid4().hex` — but uuid7 is preferred for time-sortability.

- [ ] **Step 4.3: Run ID tests pass**

Run: `pytest tests/unit/test_ids.py -v`
Expected: 4 PASSED.

- [ ] **Step 4.4: Write failing test `tests/unit/test_errors.py`**

```python
"""Tests for gateway error types."""
from __future__ import annotations

import pytest

from gateway.errors import (
    ColdStorageUnavailableError,
    FeatureNotSupportedError,
    GatewayError,
    PreviousResponseExpiredError,
    PreviousResponseNotFoundError,
    PreviousResponseProviderMismatchError,
    StorageUnavailableError,
)


def test_feature_not_supported_has_status_422() -> None:
    err = FeatureNotSupportedError(feature="web_search", param="tools[0].type", provider="dashscope")
    assert err.status_code == 422
    assert err.error_type == "feature_not_supported"
    body = err.to_response_body()
    assert body["error"]["type"] == "feature_not_supported"
    assert body["error"]["param"] == "tools[0].type"
    assert "web_search" in body["error"]["message"]


def test_previous_response_not_found_is_404() -> None:
    err = PreviousResponseNotFoundError(previous_response_id="resp_xxx")
    assert err.status_code == 404
    assert err.error_type == "previous_response_not_found"


def test_previous_response_expired_is_410() -> None:
    err = PreviousResponseExpiredError(previous_response_id="resp_xxx")
    assert err.status_code == 410


def test_provider_mismatch_is_409() -> None:
    err = PreviousResponseProviderMismatchError(parent_provider="dashscope", current_provider="deepseek")
    assert err.status_code == 409


def test_storage_unavailable_is_503() -> None:
    err = StorageUnavailableError("connection refused")
    assert err.status_code == 503


def test_cold_storage_read_unavailable_is_503() -> None:
    err = ColdStorageUnavailableError("S3 timeout")
    assert err.status_code == 503


def test_gateway_error_is_base() -> None:
    assert issubclass(FeatureNotSupportedError, GatewayError)
```

Run: `pytest tests/unit/test_errors.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 4.5: Implement `gateway/errors.py`**

```python
"""Gateway error types. Each carries an HTTP status code and an OpenAI-shaped error body."""
from __future__ import annotations

from typing import Any


class GatewayError(Exception):
    status_code: int = 500
    error_type: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, param: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.param = param

    def to_response_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {
                "type": self.error_type,
                "message": self.message,
            }
        }
        if self.code:
            body["error"]["code"] = self.code
        if self.param:
            body["error"]["param"] = self.param
        return body


class FeatureNotSupportedError(GatewayError):
    status_code = 422
    error_type = "feature_not_supported"

    def __init__(
        self,
        *,
        feature: str,
        param: str,
        provider: str | None = None,
        workaround_url: str | None = None,
    ) -> None:
        msg = f"{feature} is not yet supported"
        if provider:
            msg += f" for provider '{provider}'"
        if workaround_url:
            msg += f". Track at {workaround_url}"
        super().__init__(msg, code="feature_not_supported", param=param)
        self.feature = feature
        self.provider = provider


class PreviousResponseNotFoundError(GatewayError):
    status_code = 404
    error_type = "previous_response_not_found"

    def __init__(self, *, previous_response_id: str) -> None:
        super().__init__(
            f"previous_response_id '{previous_response_id}' not found",
            param="previous_response_id",
        )


class PreviousResponseExpiredError(GatewayError):
    status_code = 410
    error_type = "previous_response_expired"

    def __init__(self, *, previous_response_id: str) -> None:
        super().__init__(
            f"previous_response_id '{previous_response_id}' has expired",
            param="previous_response_id",
        )


class PreviousResponseProviderMismatchError(GatewayError):
    status_code = 409
    error_type = "previous_response_provider_mismatch"

    def __init__(self, *, parent_provider: str, current_provider: str) -> None:
        super().__init__(
            f"chained response was for provider '{parent_provider}' but current request "
            f"targets provider '{current_provider}'; cannot reuse session across providers",
            param="model",
        )


class ColdStorageUnavailableError(GatewayError):
    status_code = 503
    error_type = "cold_storage_unavailable"


class StorageUnavailableError(GatewayError):
    status_code = 503
    error_type = "storage_unavailable"


class ProviderError(GatewayError):
    """Wraps a LiteLLM/provider failure for client visibility."""

    error_type = "provider_error"

    def __init__(self, message: str, *, status_code: int, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}

    def to_response_body(self) -> dict[str, Any]:
        body = super().to_response_body()
        if self.details:
            body["error"]["details"] = self.details
        return body
```

- [ ] **Step 4.6: Implement `gateway/logging_setup.py`**

```python
"""Structured logging configuration."""
from __future__ import annotations

import logging
import sys
from typing import Literal

import structlog


def configure_logging(level: str = "info", format_: Literal["json", "console"] = "json") -> None:
    """Set up structlog. Call once at app startup."""
    level_int = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=level_int, stream=sys.stdout, format="%(message)s")

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if format_ == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

- [ ] **Step 4.7: Run all unit tests for this task**

Run: `pytest tests/unit/test_ids.py tests/unit/test_errors.py -v`
Expected: 11 PASSED.

- [ ] **Step 4.8: Commit**

```bash
git add gateway/ids.py gateway/errors.py gateway/logging_setup.py tests/unit/test_ids.py tests/unit/test_errors.py
git commit -m "feat(core): IDs, error types, structured logging setup"
```

---

### Task 5: Database models + Alembic init

**Spec ref:** §5 Storage Schema
**GitHub issue:** #7
**Depends on:** Task 1
**Files:**
- Create: `gateway/session/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/.keep`
- Create: `alembic/versions/<hash>_initial_sessions_table.py` (auto-generated)

- [ ] **Step 5.1: Create `gateway/session/models.py`**

```python
"""SQLAlchemy ORM models for the gateway."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all gateway ORM models."""


class SessionRow(Base):
    """One row per stored Responses-API response (when `store=true`).

    `session_id` groups all rows in a single conversation chain.
    `parent_id` points at the immediate previous_response_id (None for chain root).
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cold_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    ttl_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
```

- [ ] **Step 5.2: Initialize Alembic**

```bash
alembic init -t async alembic
```

This creates `alembic.ini` and `alembic/` skeleton. Now patch `alembic/env.py`.

- [ ] **Step 5.3: Patch `alembic/env.py`**

Replace the file with:

```python
"""Alembic env: load metadata from gateway models and DB url from GATEWAY_STORAGE__URL or alembic.ini."""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from gateway.session.models import Base

config = context.config

# Override DB URL from env if set
db_url = os.getenv("GATEWAY_STORAGE__URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 5.4: Set default URL in `alembic.ini`**

In `alembic.ini`, replace the `sqlalchemy.url` line with:

```ini
sqlalchemy.url = sqlite+aiosqlite:///./data/sessions.db
```

(Env override `GATEWAY_STORAGE__URL` takes precedence at runtime.)

- [ ] **Step 5.5: Generate initial migration**

```bash
mkdir -p data
alembic revision --autogenerate -m "initial sessions table"
```

Inspect the generated file in `alembic/versions/<hash>_initial_sessions_table.py`. It should contain `op.create_table("sessions", ...)` matching the model.

- [ ] **Step 5.6: Run migration and verify**

```bash
alembic upgrade head
sqlite3 data/sessions.db ".schema sessions"
```

Expected output contains `CREATE TABLE sessions (...id VARCHAR(64) NOT NULL, session_id VARCHAR(64), ...)` plus indexes.

- [ ] **Step 5.7: Commit**

```bash
git add gateway/session/models.py alembic.ini alembic/
git commit -m "feat(db): SQLAlchemy SessionRow model + Alembic initial migration"
```

---

### Task 6: SessionStore (async CRUD)

**Spec ref:** §3, §5
**GitHub issue:** #7
**Depends on:** Task 5
**Files:**
- Create: `gateway/session/store.py`
- Create: `tests/integration/test_session_store_sqlite.py`
- Create: `tests/integration/test_session_store_postgres.py`

- [ ] **Step 6.1: Write failing test `tests/integration/test_session_store_sqlite.py`**

```python
"""Integration tests for SessionStore against SQLite (in-memory)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gateway.session.models import Base
from gateway.session.store import SessionStore, SessionRecord


@pytest.fixture
async def store() -> SessionStore:
    s = SessionStore("sqlite+aiosqlite:///:memory:")
    await s.create_schema(Base.metadata)
    return s


async def test_insert_then_get_by_id(store: SessionStore) -> None:
    rec = SessionRecord(
        id="resp_a",
        session_id="sess_1",
        parent_id=None,
        model="deepseek-chat",
        provider="deepseek",
        input_json={"input": "hi"},
        output_json={"output": [{"type": "message"}]},
        usage_json=None,
        cold_storage_key=None,
        created_at=datetime.now(UTC),
        ttl_at=None,
    )
    await store.insert(rec)
    got = await store.get_by_id("resp_a")
    assert got is not None
    assert got.id == "resp_a"
    assert got.model == "deepseek-chat"


async def test_get_by_id_missing_returns_none(store: SessionStore) -> None:
    assert await store.get_by_id("resp_nope") is None


async def test_list_by_session_id_returns_chain_in_order(store: SessionStore) -> None:
    base = datetime.now(UTC)
    for i in range(3):
        await store.insert(
            SessionRecord(
                id=f"resp_{i}",
                session_id="sess_chain",
                parent_id=f"resp_{i - 1}" if i > 0 else None,
                model="deepseek-chat",
                provider="deepseek",
                input_json={"input": f"msg {i}"},
                output_json={"output": []},
                usage_json=None,
                cold_storage_key=None,
                created_at=base + timedelta(seconds=i),
                ttl_at=None,
            )
        )
    chain = await store.list_by_session_id("sess_chain")
    assert [r.id for r in chain] == ["resp_0", "resp_1", "resp_2"]


async def test_delete_expired_removes_only_expired(store: SessionStore) -> None:
    now = datetime.now(UTC)
    await store.insert(
        SessionRecord(
            id="resp_expired",
            session_id="s1",
            parent_id=None,
            model="m",
            provider="p",
            input_json=None,
            output_json=None,
            usage_json=None,
            cold_storage_key=None,
            created_at=now - timedelta(days=10),
            ttl_at=now - timedelta(days=1),
        )
    )
    await store.insert(
        SessionRecord(
            id="resp_alive",
            session_id="s2",
            parent_id=None,
            model="m",
            provider="p",
            input_json=None,
            output_json=None,
            usage_json=None,
            cold_storage_key=None,
            created_at=now,
            ttl_at=now + timedelta(days=1),
        )
    )
    deleted = await store.delete_expired(as_of=now)
    assert deleted == 1
    assert await store.get_by_id("resp_expired") is None
    assert await store.get_by_id("resp_alive") is not None
```

Run: `pytest tests/integration/test_session_store_sqlite.py -v`
Expected: FAIL `ModuleNotFoundError: gateway.session.store`.

- [ ] **Step 6.2: Implement `gateway/session/store.py`**

```python
"""Async SessionStore — DB CRUD for the sessions table."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.session.models import SessionRow


@dataclass
class SessionRecord:
    """Plain-data representation of a session row (no SQLAlchemy state attached)."""

    id: str
    session_id: str
    parent_id: str | None
    model: str
    provider: str
    input_json: dict[str, Any] | None
    output_json: dict[str, Any] | None
    usage_json: dict[str, Any] | None
    cold_storage_key: str | None
    created_at: datetime
    ttl_at: datetime | None

    @classmethod
    def from_row(cls, row: SessionRow) -> "SessionRecord":
        return cls(
            id=row.id,
            session_id=row.session_id,
            parent_id=row.parent_id,
            model=row.model,
            provider=row.provider,
            input_json=row.input_json,
            output_json=row.output_json,
            usage_json=row.usage_json,
            cold_storage_key=row.cold_storage_key,
            created_at=row.created_at,
            ttl_at=row.ttl_at,
        )

    def to_row(self) -> SessionRow:
        return SessionRow(
            id=self.id,
            session_id=self.session_id,
            parent_id=self.parent_id,
            model=self.model,
            provider=self.provider,
            input_json=self.input_json,
            output_json=self.output_json,
            usage_json=self.usage_json,
            cold_storage_key=self.cold_storage_key,
            created_at=self.created_at,
            ttl_at=self.ttl_at,
        )


class SessionStore:
    def __init__(self, db_url: str) -> None:
        self._engine = create_async_engine(db_url, future=True)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def create_schema(self, metadata: MetaData) -> None:
        """For tests only. Production uses Alembic migrations."""
        async with self._engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def insert(self, record: SessionRecord) -> None:
        async with self._sessionmaker() as session:
            session.add(record.to_row())
            await session.commit()

    async def get_by_id(self, response_id: str) -> SessionRecord | None:
        async with self._sessionmaker() as session:
            row = await session.get(SessionRow, response_id)
            return SessionRecord.from_row(row) if row else None

    async def list_by_session_id(self, session_id: str) -> list[SessionRecord]:
        async with self._sessionmaker() as session:
            stmt = (
                select(SessionRow)
                .where(SessionRow.session_id == session_id)
                .order_by(SessionRow.created_at.asc())
            )
            result = await session.execute(stmt)
            return [SessionRecord.from_row(r) for r in result.scalars().all()]

    async def delete_expired(self, as_of: datetime) -> int:
        async with self._sessionmaker() as session:
            stmt = delete(SessionRow).where(
                SessionRow.ttl_at.is_not(None), SessionRow.ttl_at < as_of
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def close(self) -> None:
        await self._engine.dispose()
```

- [ ] **Step 6.3: Run SQLite tests pass**

Run: `pytest tests/integration/test_session_store_sqlite.py -v`
Expected: 4 PASSED.

- [ ] **Step 6.4: Write Postgres equivalent `tests/integration/test_session_store_postgres.py`**

```python
"""Same tests as SQLite version, but against a real Postgres (skip if not available)."""
from __future__ import annotations

import os

import pytest

from gateway.session.models import Base
from gateway.session.store import SessionStore

POSTGRES_URL = os.getenv("GATEWAY_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL or os.getenv("GATEWAY_TEST_STORAGE", "sqlite") != "postgres",
    reason="Postgres URL not configured",
)


@pytest.fixture
async def store() -> SessionStore:
    assert POSTGRES_URL  # for mypy
    s = SessionStore(POSTGRES_URL)
    await s.create_schema(Base.metadata)
    yield s
    # Drop tables between tests
    async with s._engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await s.close()


# Re-import the SQLite test cases to get coverage on Postgres too
from tests.integration.test_session_store_sqlite import (  # noqa: E402
    test_delete_expired_removes_only_expired,
    test_get_by_id_missing_returns_none,
    test_insert_then_get_by_id,
    test_list_by_session_id_returns_chain_in_order,
)
```

- [ ] **Step 6.5: Verify Postgres test is skipped without env**

Run: `pytest tests/integration/test_session_store_postgres.py -v`
Expected: 4 SKIPPED.

- [ ] **Step 6.6: Commit**

```bash
git add gateway/session/store.py tests/integration/
git commit -m "feat(session): async SessionStore with SQLite + Postgres integration tests"
```

---

### Task 7: ColdStorage interface

**Spec ref:** §5 Offload, §7 Error Handling
**Depends on:** Task 1, Task 4 (errors)
**Files:**
- Create: `gateway/storage/cold.py`
- Create: `tests/unit/test_cold_storage_inmem.py`

- [ ] **Step 7.1: Write failing test `tests/unit/test_cold_storage_inmem.py`**

```python
"""Tests for the in-memory ColdStorage implementation (used in tests + dev)."""
from __future__ import annotations

import pytest

from gateway.errors import ColdStorageUnavailableError
from gateway.storage.cold import ColdStorage, InMemoryColdStorage


def test_inmem_storage_roundtrip() -> None:
    cs: ColdStorage = InMemoryColdStorage()
    payload = {"input": [{"role": "user", "content": "hi"}], "output": [{"type": "message"}]}
    key = cs.put_sync(payload)  # InMemory provides sync helpers for tests
    fetched = cs.get_sync(key)
    assert fetched == payload


def test_inmem_get_missing_raises() -> None:
    cs = InMemoryColdStorage()
    with pytest.raises(ColdStorageUnavailableError):
        cs.get_sync("nonexistent-key")


async def test_inmem_storage_async_api() -> None:
    cs: ColdStorage = InMemoryColdStorage()
    key = await cs.put({"a": 1})
    fetched = await cs.get(key)
    assert fetched == {"a": 1}
```

Run: `pytest tests/unit/test_cold_storage_inmem.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 7.2: Implement `gateway/storage/cold.py`**

```python
"""Cold storage backend for large session payloads. Optional and pluggable."""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Protocol

from gateway.errors import ColdStorageUnavailableError


class ColdStorage(Protocol):
    """Backend protocol for offloaded payload storage. All ops are async."""

    async def put(self, payload: dict[str, Any]) -> str:
        """Store payload, return opaque object key."""
        ...

    async def get(self, key: str) -> dict[str, Any]:
        """Retrieve payload by key. Raises ColdStorageUnavailableError on failure."""
        ...


class InMemoryColdStorage:
    """In-memory backend for tests and single-process dev."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def put_sync(self, payload: dict[str, Any]) -> str:
        key = uuid.uuid4().hex
        self._data[key] = json.dumps(payload).encode()
        return key

    def get_sync(self, key: str) -> dict[str, Any]:
        if key not in self._data:
            raise ColdStorageUnavailableError(f"cold storage key not found: {key}")
        return json.loads(self._data[key])

    async def put(self, payload: dict[str, Any]) -> str:
        return await asyncio.to_thread(self.put_sync, payload)

    async def get(self, key: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_sync, key)


class S3ColdStorage:
    """S3-backed cold storage. Requires `aioboto3` (install extra `s3`).

    Only stores JSON-serializable payloads. `bucket_url` format: `s3://bucket-name/optional-prefix`.
    """

    def __init__(self, bucket_url: str) -> None:
        if not bucket_url.startswith("s3://"):
            raise ValueError(f"Invalid S3 bucket URL: {bucket_url}")
        rest = bucket_url[5:]
        parts = rest.split("/", 1)
        self._bucket = parts[0]
        self._prefix = parts[1].rstrip("/") + "/" if len(parts) == 2 and parts[1] else ""

    async def put(self, payload: dict[str, Any]) -> str:
        import aioboto3

        key = f"{self._prefix}{uuid.uuid4().hex}.json"
        try:
            async with aioboto3.Session().client("s3") as s3:
                await s3.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=json.dumps(payload).encode(),
                    ContentType="application/json",
                )
            return key
        except Exception as exc:
            raise ColdStorageUnavailableError(f"S3 put failed: {exc}") from exc

    async def get(self, key: str) -> dict[str, Any]:
        import aioboto3

        try:
            async with aioboto3.Session().client("s3") as s3:
                resp = await s3.get_object(Bucket=self._bucket, Key=key)
                body = await resp["Body"].read()
                return json.loads(body)
        except Exception as exc:
            raise ColdStorageUnavailableError(f"S3 get failed: {exc}") from exc


def build_cold_storage(*, enabled: bool, backend: str, bucket_url: str | None) -> ColdStorage | None:
    """Factory: returns None if disabled."""
    if not enabled:
        return None
    if backend == "inmem":
        return InMemoryColdStorage()
    if backend == "s3":
        if not bucket_url:
            raise ValueError("cold.bucket_url required when backend=s3")
        return S3ColdStorage(bucket_url)
    raise ValueError(f"unknown cold storage backend: {backend}")
```

- [ ] **Step 7.3: Run cold storage tests pass**

Run: `pytest tests/unit/test_cold_storage_inmem.py -v`
Expected: 3 PASSED.

- [ ] **Step 7.4: Commit**

```bash
git add gateway/storage/ tests/unit/test_cold_storage_inmem.py
git commit -m "feat(storage): cold storage interface, in-memory backend, S3 backend"
```

---

### Task 8: Validator (rejection layer)

**Spec ref:** §7 Error Handling, issue #1
**GitHub issue:** #1
**Depends on:** Task 3, Task 4
**Files:**
- Create: `gateway/validator.py`
- Create: `tests/unit/test_validator.py`

- [ ] **Step 8.1: Write failing test `tests/unit/test_validator.py`**

```python
"""Tests for the rejection validator (issue #1)."""
from __future__ import annotations

import pytest

from gateway.config import RejectConfig
from gateway.errors import FeatureNotSupportedError
from gateway.validator import Validator


@pytest.fixture
def validator() -> Validator:
    return Validator(RejectConfig())  # default rejects web_search, code_interpreter, etc.


def test_passes_function_tool(validator: Validator) -> None:
    request = {
        "input": "hi",
        "tools": [{"type": "function", "name": "f", "parameters": {"type": "object"}}],
    }
    validator.validate(request)


def test_rejects_web_search_tool(validator: Validator) -> None:
    request = {"input": "hi", "tools": [{"type": "web_search"}]}
    with pytest.raises(FeatureNotSupportedError) as exc:
        validator.validate(request)
    assert exc.value.feature == "web_search"
    assert exc.value.param == "tools[0].type"


def test_rejects_code_interpreter_at_index_2(validator: Validator) -> None:
    request = {
        "input": "hi",
        "tools": [
            {"type": "function", "name": "f", "parameters": {"type": "object"}},
            {"type": "function", "name": "g", "parameters": {"type": "object"}},
            {"type": "code_interpreter"},
        ],
    }
    with pytest.raises(FeatureNotSupportedError) as exc:
        validator.validate(request)
    assert exc.value.param == "tools[2].type"


def test_rejects_background_true(validator: Validator) -> None:
    with pytest.raises(FeatureNotSupportedError) as exc:
        validator.validate({"input": "hi", "background": True})
    assert exc.value.feature == "background"
    assert exc.value.param == "background"


def test_allows_background_false(validator: Validator) -> None:
    validator.validate({"input": "hi", "background": False})


def test_rejects_truncation_auto(validator: Validator) -> None:
    with pytest.raises(FeatureNotSupportedError) as exc:
        validator.validate({"input": "hi", "truncation": "auto"})
    assert exc.value.feature == "truncation"


def test_allows_truncation_disabled(validator: Validator) -> None:
    validator.validate({"input": "hi", "truncation": "disabled"})


def test_workaround_url_template_substitution(validator: Validator) -> None:
    with pytest.raises(FeatureNotSupportedError) as exc:
        validator.validate({"input": "hi", "tools": [{"type": "web_search"}]})
    # Message should contain the URL with {feature} substituted
    assert "web_search" in str(exc.value)
```

Run: `pytest tests/unit/test_validator.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 8.2: Implement `gateway/validator.py`**

```python
"""Pre-call validator that rejects features the gateway can't honor.

See issue #1 (Graceful rejection of unsupported Responses API features).
"""
from __future__ import annotations

from typing import Any

from gateway.config import RejectConfig
from gateway.errors import FeatureNotSupportedError


class Validator:
    def __init__(self, config: RejectConfig) -> None:
        self._cfg = config
        self._rejected_tool_types: set[str] = set(config.tools)

    def validate(self, request: dict[str, Any], *, provider: str | None = None) -> None:
        """Raise FeatureNotSupportedError if request contains unsupported features."""
        # Tools
        tools = request.get("tools") or []
        for i, tool in enumerate(tools):
            ttype = tool.get("type") if isinstance(tool, dict) else None
            if ttype in self._rejected_tool_types:
                raise FeatureNotSupportedError(
                    feature=ttype,
                    param=f"tools[{i}].type",
                    provider=provider,
                    workaround_url=self._cfg.workaround_url_template.format(feature=ttype),
                )

        # Top-level fields
        for field, rejected_value in self._cfg.fields.items():
            actual = request.get(field)
            # For booleans we reject only when actual matches the rejected truthy value
            if isinstance(rejected_value, bool):
                if actual is rejected_value:
                    raise FeatureNotSupportedError(
                        feature=field,
                        param=field,
                        provider=provider,
                        workaround_url=self._cfg.workaround_url_template.format(feature=field),
                    )
            else:
                if actual == rejected_value:
                    raise FeatureNotSupportedError(
                        feature=field,
                        param=field,
                        provider=provider,
                        workaround_url=self._cfg.workaround_url_template.format(feature=field),
                    )
```

- [ ] **Step 8.3: Run validator tests pass**

Run: `pytest tests/unit/test_validator.py -v`
Expected: 8 PASSED.

- [ ] **Step 8.4: Commit**

```bash
git add gateway/validator.py tests/unit/test_validator.py
git commit -m "feat(validator): reject unsupported tools and fields (#1)"
```

---

### Task 9: SessionResolver (intercept-and-translate)

**Spec ref:** §4.1 Data flow steps 3, §7 Error matrix
**GitHub issues:** #7, #16
**Depends on:** Task 6, Task 7
**Files:**
- Create: `gateway/session/resolver.py`
- Create: `tests/unit/test_session_resolver.py`

- [ ] **Step 9.1: Write failing test `tests/unit/test_session_resolver.py`**

```python
"""Tests for SessionResolver — intercepts previous_response_id and rebuilds messages."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from gateway.errors import (
    PreviousResponseExpiredError,
    PreviousResponseNotFoundError,
    PreviousResponseProviderMismatchError,
)
from gateway.session.resolver import ResolvedRequest, SessionResolver
from gateway.session.store import SessionRecord


class FakeStore:
    def __init__(self, records: list[SessionRecord]) -> None:
        self._by_id = {r.id: r for r in records}

    async def get_by_id(self, response_id: str) -> SessionRecord | None:
        return self._by_id.get(response_id)

    async def list_by_session_id(self, session_id: str) -> list[SessionRecord]:
        return sorted(
            (r for r in self._by_id.values() if r.session_id == session_id),
            key=lambda r: r.created_at,
        )


def _row(
    id_: str,
    session_id: str,
    parent_id: str | None,
    *,
    provider: str = "deepseek",
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    ttl_at: datetime | None = None,
) -> SessionRecord:
    return SessionRecord(
        id=id_,
        session_id=session_id,
        parent_id=parent_id,
        model="deepseek-chat",
        provider=provider,
        input_json=input_json or {"input": "default"},
        output_json=output_json
        or {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]},
        usage_json=None,
        cold_storage_key=None,
        created_at=datetime.now(UTC),
        ttl_at=ttl_at,
    )


async def test_no_previous_response_id_passes_through() -> None:
    resolver = SessionResolver(store=FakeStore([]), cold_storage=None)
    req: dict[str, Any] = {"input": "hello", "model": "deepseek-chat"}
    resolved = await resolver.resolve(req, current_provider="deepseek")
    assert resolved.request == req
    assert resolved.session_id is None
    assert resolved.parent_id is None


async def test_resolves_chain_into_messages_and_drops_previous_response_id() -> None:
    history = [
        _row("r1", "s1", None, input_json={"input": "first user"}, output_json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "first asst"}]}]}),
        _row("r2", "s1", "r1", input_json={"input": "second user"}, output_json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "second asst"}]}]}),
    ]
    resolver = SessionResolver(store=FakeStore(history), cold_storage=None)
    req = {"input": "third user", "model": "deepseek-chat", "previous_response_id": "r2"}
    resolved = await resolver.resolve(req, current_provider="deepseek")

    assert "previous_response_id" not in resolved.request
    assert resolved.session_id == "s1"
    assert resolved.parent_id == "r2"
    # Input should be the prepended messages followed by the current input as the last user msg
    new_input = resolved.request["input"]
    assert isinstance(new_input, list)
    # Each historical row produces (user, assistant); plus current user msg = 5 items
    assert len(new_input) == 5
    assert new_input[-1]["content"] == "third user" or new_input[-1]["content"][0]["text"] == "third user"


async def test_unknown_previous_response_id_raises_404() -> None:
    resolver = SessionResolver(store=FakeStore([]), cold_storage=None)
    with pytest.raises(PreviousResponseNotFoundError):
        await resolver.resolve(
            {"input": "x", "model": "m", "previous_response_id": "resp_missing"},
            current_provider="deepseek",
        )


async def test_expired_previous_response_id_raises_410() -> None:
    expired = _row("r1", "s1", None, ttl_at=datetime.now(UTC) - timedelta(days=1))
    resolver = SessionResolver(store=FakeStore([expired]), cold_storage=None)
    with pytest.raises(PreviousResponseExpiredError):
        await resolver.resolve(
            {"input": "x", "model": "deepseek-chat", "previous_response_id": "r1"},
            current_provider="deepseek",
        )


async def test_provider_mismatch_raises_409() -> None:
    history = [_row("r1", "s1", None, provider="dashscope")]
    resolver = SessionResolver(store=FakeStore(history), cold_storage=None)
    with pytest.raises(PreviousResponseProviderMismatchError):
        await resolver.resolve(
            {"input": "x", "model": "deepseek-chat", "previous_response_id": "r1"},
            current_provider="deepseek",
        )
```

Run: `pytest tests/unit/test_session_resolver.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 9.2: Implement `gateway/session/resolver.py`**

```python
"""SessionResolver — intercept previous_response_id and rebuild full message history.

Strategy: rather than passing previous_response_id down to LiteLLM (whose SessionHandler
requires the LiteLLM Proxy spend_logs DB), we resolve it ourselves from our own session table
and prepend reconstructed messages to the current request input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from gateway.errors import (
    PreviousResponseExpiredError,
    PreviousResponseNotFoundError,
    PreviousResponseProviderMismatchError,
)
from gateway.session.store import SessionRecord


class _StoreLike(Protocol):
    async def get_by_id(self, response_id: str) -> SessionRecord | None: ...
    async def list_by_session_id(self, session_id: str) -> list[SessionRecord]: ...


class _ColdLike(Protocol):
    async def get(self, key: str) -> dict[str, Any]: ...


@dataclass
class ResolvedRequest:
    """Request after previous_response_id resolution."""

    request: dict[str, Any]
    session_id: str | None  # None if no chain (new session)
    parent_id: str | None  # the previous_response_id used (None for new session)


class SessionResolver:
    def __init__(self, *, store: _StoreLike, cold_storage: _ColdLike | None) -> None:
        self._store = store
        self._cold = cold_storage

    async def resolve(
        self, request: dict[str, Any], *, current_provider: str
    ) -> ResolvedRequest:
        prev_id = request.get("previous_response_id")
        if not prev_id:
            return ResolvedRequest(request=request, session_id=None, parent_id=None)

        parent = await self._store.get_by_id(prev_id)
        if parent is None:
            raise PreviousResponseNotFoundError(previous_response_id=prev_id)

        if parent.ttl_at is not None and parent.ttl_at < datetime.now(UTC):
            raise PreviousResponseExpiredError(previous_response_id=prev_id)

        if parent.provider != current_provider:
            raise PreviousResponseProviderMismatchError(
                parent_provider=parent.provider, current_provider=current_provider
            )

        # Pull full chain (including parent itself) ordered by created_at
        chain = await self._store.list_by_session_id(parent.session_id)
        history_messages = await self._reconstruct_messages(chain)

        # Build new input: history + the current input items
        current_input = request.get("input", [])
        new_input = history_messages + self._normalize_current_input(current_input)

        new_request = {**request, "input": new_input}
        new_request.pop("previous_response_id", None)

        return ResolvedRequest(
            request=new_request, session_id=parent.session_id, parent_id=prev_id
        )

    async def _reconstruct_messages(self, chain: list[SessionRecord]) -> list[dict[str, Any]]:
        """Walk each historical row, append (user-input, assistant-output) pairs."""
        messages: list[dict[str, Any]] = []
        for row in chain:
            input_payload = await self._payload(row, field="input")
            output_payload = await self._payload(row, field="output")
            messages.extend(self._normalize_current_input(input_payload.get("input", [])))
            for item in output_payload.get("output", []):
                if isinstance(item, dict) and item.get("type") == "message":
                    messages.append({"role": "assistant", "content": item.get("content", [])})
                # function_call items: pass through as-is so model sees its own tool calls
                elif isinstance(item, dict) and item.get("type") == "function_call":
                    messages.append(item)
        return messages

    async def _payload(self, row: SessionRecord, *, field: str) -> dict[str, Any]:
        """Read input or output JSON, falling back to cold storage if offloaded."""
        if row.cold_storage_key:
            assert self._cold is not None, "cold storage required but not configured"
            full = await self._cold.get(row.cold_storage_key)
            return {field: full.get(field, [])}

        if field == "input":
            return row.input_json or {"input": []}
        return row.output_json or {"output": []}

    @staticmethod
    def _normalize_current_input(current: Any) -> list[dict[str, Any]]:
        """Coerce the various Responses input shapes into a list of message-like dicts."""
        if isinstance(current, str):
            return [{"role": "user", "content": current}]
        if isinstance(current, list):
            return list(current)
        if isinstance(current, dict):
            return [current]
        return []
```

- [ ] **Step 9.3: Run resolver tests pass**

Run: `pytest tests/unit/test_session_resolver.py -v`
Expected: 5 PASSED.

- [ ] **Step 9.4: Commit**

```bash
git add gateway/session/resolver.py tests/unit/test_session_resolver.py
git commit -m "feat(session): SessionResolver intercept-and-translate (#7)"
```

---

### Task 10: SessionRecorder

**Spec ref:** §4.1 step 5, §5
**GitHub issue:** #7
**Depends on:** Task 6, Task 7
**Files:**
- Create: `gateway/session/recorder.py`
- Create: `tests/unit/test_session_recorder.py`

- [ ] **Step 10.1: Write failing test `tests/unit/test_session_recorder.py`**

```python
"""Tests for SessionRecorder — persists new responses post-call."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from gateway.session.recorder import SessionRecorder
from gateway.session.store import SessionRecord
from gateway.storage.cold import InMemoryColdStorage


class CapturingStore:
    def __init__(self) -> None:
        self.records: list[SessionRecord] = []

    async def insert(self, rec: SessionRecord) -> None:
        self.records.append(rec)


async def test_recorder_stores_new_session_when_no_parent() -> None:
    store = CapturingStore()
    recorder = SessionRecorder(
        store=store, cold_storage=None, ttl_days=30, threshold_bytes=1_048_576
    )
    new_id = await recorder.record(
        original_request={"input": "hi", "model": "deepseek-chat"},
        response_payload={"id": "ignored", "output": [{"type": "message"}], "usage": {"input_tokens": 5}},
        provider="deepseek",
        model="deepseek-chat",
        session_id=None,
        parent_id=None,
        store_flag=True,
    )
    assert new_id.startswith("resp_")
    assert len(store.records) == 1
    rec = store.records[0]
    assert rec.id == new_id
    assert rec.parent_id is None
    assert rec.session_id  # newly generated
    assert rec.input_json == {"input": "hi", "model": "deepseek-chat"}
    assert rec.cold_storage_key is None
    assert rec.ttl_at is not None
    assert rec.ttl_at > datetime.now(UTC) + timedelta(days=29)


async def test_recorder_inherits_session_id_from_chain() -> None:
    store = CapturingStore()
    recorder = SessionRecorder(
        store=store, cold_storage=None, ttl_days=30, threshold_bytes=1_048_576
    )
    new_id = await recorder.record(
        original_request={"input": "msg2"},
        response_payload={"output": []},
        provider="deepseek",
        model="m",
        session_id="sess_existing",
        parent_id="resp_prev",
        store_flag=True,
    )
    rec = store.records[0]
    assert rec.session_id == "sess_existing"
    assert rec.parent_id == "resp_prev"


async def test_recorder_skips_when_store_false() -> None:
    store = CapturingStore()
    recorder = SessionRecorder(
        store=store, cold_storage=None, ttl_days=30, threshold_bytes=1_048_576
    )
    new_id = await recorder.record(
        original_request={"input": "hi"},
        response_payload={"output": []},
        provider="deepseek",
        model="m",
        session_id=None,
        parent_id=None,
        store_flag=False,
    )
    # Still returns a generated id (so client gets one) but does not persist
    assert new_id.startswith("resp_")
    assert store.records == []


async def test_recorder_offloads_to_cold_storage_when_over_threshold() -> None:
    store = CapturingStore()
    cold = InMemoryColdStorage()
    # Threshold 100 bytes — easy to exceed
    recorder = SessionRecorder(store=store, cold_storage=cold, ttl_days=30, threshold_bytes=100)
    big_input = {"input": "x" * 200}
    big_output = {"output": [{"type": "message", "content": "y" * 200}]}
    await recorder.record(
        original_request=big_input,
        response_payload=big_output,
        provider="deepseek",
        model="m",
        session_id=None,
        parent_id=None,
        store_flag=True,
    )
    rec = store.records[0]
    assert rec.cold_storage_key is not None
    assert rec.input_json is None
    assert rec.output_json is None
    # Cold storage should hold the full payload
    full = cold.get_sync(rec.cold_storage_key)
    assert full == {"input": big_input, "output": big_output}


async def test_recorder_falls_back_inline_on_cold_write_failure() -> None:
    store = CapturingStore()

    class ExplodingCold:
        async def put(self, payload: dict[str, Any]) -> str:
            raise RuntimeError("S3 down")

        async def get(self, key: str) -> dict[str, Any]:
            raise RuntimeError("S3 down")

    recorder = SessionRecorder(
        store=store, cold_storage=ExplodingCold(), ttl_days=30, threshold_bytes=1
    )
    await recorder.record(
        original_request={"input": "hi"},
        response_payload={"output": []},
        provider="deepseek",
        model="m",
        session_id=None,
        parent_id=None,
        store_flag=True,
    )
    rec = store.records[0]
    # Fell back to inline
    assert rec.cold_storage_key is None
    assert rec.input_json == {"input": "hi"}
```

Run: `pytest tests/unit/test_session_recorder.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 10.2: Implement `gateway/session/recorder.py`**

```python
"""SessionRecorder — persists a completed Responses-API call to the session table."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from gateway.ids import new_response_id, new_session_id
from gateway.logging_setup import get_logger
from gateway.session.store import SessionRecord


class _StoreLike(Protocol):
    async def insert(self, record: SessionRecord) -> None: ...


class _ColdLike(Protocol):
    async def put(self, payload: dict[str, Any]) -> str: ...


_log = get_logger(__name__)


class SessionRecorder:
    def __init__(
        self,
        *,
        store: _StoreLike,
        cold_storage: _ColdLike | None,
        ttl_days: int,
        threshold_bytes: int,
    ) -> None:
        self._store = store
        self._cold = cold_storage
        self._ttl = timedelta(days=ttl_days)
        self._threshold = threshold_bytes

    async def record(
        self,
        *,
        original_request: dict[str, Any],
        response_payload: dict[str, Any],
        provider: str,
        model: str,
        session_id: str | None,
        parent_id: str | None,
        store_flag: bool,
    ) -> str:
        """Record a finished call. Returns the new response id (always generated)."""
        new_id = new_response_id()
        if not store_flag:
            return new_id

        sid = session_id or new_session_id()
        now = datetime.now(UTC)
        ttl_at = now + self._ttl

        rec = SessionRecord(
            id=new_id,
            session_id=sid,
            parent_id=parent_id,
            model=model,
            provider=provider,
            input_json=original_request,
            output_json=response_payload,
            usage_json=response_payload.get("usage"),
            cold_storage_key=None,
            created_at=now,
            ttl_at=ttl_at,
        )

        # Cold offload if over threshold
        size = len(json.dumps(original_request)) + len(json.dumps(response_payload))
        if self._cold is not None and size > self._threshold:
            try:
                key = await self._cold.put(
                    {"input": original_request, "output": response_payload}
                )
                rec.input_json = None
                rec.output_json = None
                rec.cold_storage_key = key
            except Exception as exc:
                _log.warn(
                    "cold_storage_write_failed_falling_back_inline",
                    error=str(exc),
                    response_id=new_id,
                )

        await self._store.insert(rec)
        return new_id
```

- [ ] **Step 10.3: Run recorder tests pass**

Run: `pytest tests/unit/test_session_recorder.py -v`
Expected: 5 PASSED.

- [ ] **Step 10.4: Commit**

```bash
git add gateway/session/recorder.py tests/unit/test_session_recorder.py
git commit -m "feat(session): SessionRecorder with cold-offload fallback (#7)"
```

---

### Task 11: LLMRouter (litellm.aresponses wrapper)

**Spec ref:** §3, §4.1 step 4
**Depends on:** Task 3
**Files:**
- Create: `gateway/llm.py`
- Create: `tests/unit/test_llm.py`

- [ ] **Step 11.1: Write failing test `tests/unit/test_llm.py`**

```python
"""Tests for the LiteLLM wrapper."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from gateway.config import LiteLLMConfig
from gateway.errors import ProviderError
from gateway.llm import LLMRouter, provider_from_model


def test_provider_from_model_extracts_prefix() -> None:
    assert provider_from_model("dashscope/qwen-max") == "dashscope"
    assert provider_from_model("deepseek/deepseek-chat") == "deepseek"
    assert provider_from_model("gpt-4o") == "openai"  # no prefix → fall back to openai
    assert provider_from_model("openrouter/anthropic/claude-3.5") == "openrouter"


async def test_router_calls_litellm_aresponses() -> None:
    fake_response = {"id": "resp_x", "output": [{"type": "message"}], "usage": {}}
    router = LLMRouter(LiteLLMConfig())
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_response)) as m:
        result = await router.call(
            request={"input": "hi", "model": "deepseek/deepseek-chat"},
        )
    assert result == fake_response
    m.assert_awaited_once()
    kwargs = m.await_args.kwargs
    assert kwargs["model"] == "deepseek/deepseek-chat"
    assert kwargs["input"] == "hi"
    assert kwargs["timeout"] == 60


async def test_router_wraps_litellm_error_as_provider_error() -> None:
    router = LLMRouter(LiteLLMConfig())

    class FakeLLMError(Exception):
        status_code = 429
        message = "rate limited"

    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(side_effect=FakeLLMError("rate limited"))):
        with pytest.raises(ProviderError) as exc:
            await router.call(request={"input": "hi", "model": "deepseek/deepseek-chat"})
    assert exc.value.status_code == 429
```

Run: `pytest tests/unit/test_llm.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 11.2: Implement `gateway/llm.py`**

```python
"""Thin wrapper around `litellm.aresponses`. The only LLM dependency in the gateway."""
from __future__ import annotations

from typing import Any, AsyncIterator

import litellm

from gateway.config import LiteLLMConfig
from gateway.errors import ProviderError


def provider_from_model(model: str) -> str:
    """Extract provider prefix. `dashscope/qwen-max` → `dashscope`. No slash → 'openai'."""
    if "/" not in model:
        return "openai"
    return model.split("/", 1)[0]


class LLMRouter:
    def __init__(self, config: LiteLLMConfig) -> None:
        self._cfg = config
        # If a model_list_path is configured, register it with litellm
        if config.model_list_path:
            try:
                import yaml

                with open(config.model_list_path) as f:
                    cfg = yaml.safe_load(f)
                if isinstance(cfg, dict) and "model_list" in cfg:
                    litellm.set_verbose = False  # honor user log level
                    # Register models via Router not strictly needed; litellm.aresponses
                    # picks up env keys directly. Loading the list lets users define api_base etc.
                    # We rely on litellm's own config loading via env or programmatic registration.
            except FileNotFoundError:
                pass

    async def call(self, *, request: dict[str, Any]) -> dict[str, Any]:
        """Non-streaming call."""
        try:
            return await litellm.aresponses(
                **request,
                timeout=self._cfg.request_timeout,
                num_retries=self._cfg.num_retries,
            )
        except Exception as exc:
            raise self._wrap(exc) from exc

    async def stream(self, *, request: dict[str, Any]) -> AsyncIterator[Any]:
        """Streaming call. Returns an async iterator over Responses events."""
        try:
            iterator = await litellm.aresponses(
                **request,
                stream=True,
                timeout=self._cfg.request_timeout,
                num_retries=self._cfg.num_retries,
            )
            async for event in iterator:
                yield event
        except Exception as exc:
            raise self._wrap(exc) from exc

    @staticmethod
    def _wrap(exc: Exception) -> ProviderError:
        status = getattr(exc, "status_code", 502)
        details = {}
        for attr in ("type", "code", "param"):
            v = getattr(exc, attr, None)
            if v is not None:
                details[attr] = v
        return ProviderError(message=str(exc), status_code=int(status), details=details)
```

- [ ] **Step 11.3: Run LLM tests pass**

Run: `pytest tests/unit/test_llm.py -v`
Expected: 3 PASSED.

- [ ] **Step 11.4: Commit**

```bash
git add gateway/llm.py tests/unit/test_llm.py
git commit -m "feat(llm): LiteLLM aresponses wrapper with provider mapping"
```

---

### Task 12: StreamBridge

**Spec ref:** §4.2 Streaming
**GitHub issue:** #14
**Depends on:** —
**Files:**
- Create: `gateway/streaming.py`
- Create: `tests/unit/test_streaming.py`

- [ ] **Step 12.1: Write failing test `tests/unit/test_streaming.py`**

```python
"""Tests for StreamBridge — tee streaming events while building final state."""
from __future__ import annotations

from typing import Any

import pytest

from gateway.streaming import StreamBridge


def _evt(t: str, **kwargs: Any) -> dict[str, Any]:
    return {"type": t, **kwargs}


async def test_bridge_forwards_all_events_and_builds_final_state() -> None:
    events = [
        _evt("response.created", response={"id": "resp_x", "output": []}),
        _evt("response.output_item.added", item={"type": "message", "id": "msg_1"}),
        _evt("response.content_part.added", part={"type": "output_text"}),
        _evt("response.output_text.delta", delta="Hel"),
        _evt("response.output_text.delta", delta="lo"),
        _evt("response.output_text.done", text="Hello"),
        _evt("response.output_item.done", item={"type": "message", "id": "msg_1", "content": [{"type": "output_text", "text": "Hello"}]}),
        _evt("response.completed", response={"id": "resp_x", "output": [], "usage": {"input_tokens": 1, "output_tokens": 2}}),
    ]

    bridge = StreamBridge()
    forwarded: list[dict[str, Any]] = []

    async def src():
        for e in events:
            yield e

    async for evt in bridge.tee(src()):
        forwarded.append(evt)

    assert forwarded == events
    final = bridge.final_state()
    # Final state holds the merged output_text and usage from response.completed
    assert final["usage"]["input_tokens"] == 1
    assert any(item["content"][0]["text"] == "Hello" for item in final["output"] if item.get("type") == "message")


async def test_bridge_handles_function_call_arguments_delta() -> None:
    events = [
        _evt("response.created", response={"id": "resp_y", "output": []}),
        _evt("response.output_item.added", item={"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "search", "arguments": ""}),
        _evt("response.function_call_arguments.delta", item_id="fc_1", delta='{"q":"'),
        _evt("response.function_call_arguments.delta", item_id="fc_1", delta='hi"}'),
        _evt("response.function_call_arguments.done", item_id="fc_1", arguments='{"q":"hi"}'),
        _evt("response.output_item.done", item={"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "search", "arguments": '{"q":"hi"}'}),
        _evt("response.completed", response={"id": "resp_y", "output": [], "usage": {}}),
    ]
    bridge = StreamBridge()

    async def src():
        for e in events:
            yield e

    async for _ in bridge.tee(src()):
        pass

    final = bridge.final_state()
    fc_items = [it for it in final["output"] if it.get("type") == "function_call"]
    assert len(fc_items) == 1
    assert fc_items[0]["arguments"] == '{"q":"hi"}'
```

Run: `pytest tests/unit/test_streaming.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 12.2: Implement `gateway/streaming.py`**

```python
"""Streaming bridge: tee Responses-API events while accumulating the final state.

The final state mirrors what a non-streaming response would have looked like, so
SessionRecorder can persist it consistently regardless of streaming mode.
"""
from __future__ import annotations

from typing import Any, AsyncIterator


class StreamBridge:
    def __init__(self) -> None:
        self._items_by_id: dict[str, dict[str, Any]] = {}
        self._item_order: list[str] = []
        self._final_response: dict[str, Any] = {"output": [], "usage": {}}

    async def tee(self, source: AsyncIterator[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        """Forward each event downstream while updating internal final-state buffer."""
        async for event in source:
            self._consume(event)
            yield event

    def _consume(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "response.created":
            resp = event.get("response", {})
            self._final_response.update(resp)
            self._final_response.setdefault("output", [])
            self._final_response.setdefault("usage", {})
            return
        if etype == "response.output_item.added":
            item = event.get("item", {})
            iid = item.get("id")
            if iid:
                self._items_by_id[iid] = dict(item)
                self._item_order.append(iid)
            return
        if etype == "response.output_text.delta":
            # Latest output_text item gets the delta appended
            item = self._latest_item_of_type("message")
            if item:
                content = item.setdefault("content", [])
                if not content or content[-1].get("type") != "output_text":
                    content.append({"type": "output_text", "text": ""})
                content[-1]["text"] += event.get("delta", "")
            return
        if etype == "response.function_call_arguments.delta":
            iid = event.get("item_id")
            if iid and iid in self._items_by_id:
                self._items_by_id[iid]["arguments"] = (
                    self._items_by_id[iid].get("arguments", "") + event.get("delta", "")
                )
            return
        if etype == "response.output_item.done":
            item = event.get("item", {})
            iid = item.get("id")
            if iid:
                self._items_by_id[iid] = dict(item)
            return
        if etype == "response.completed":
            resp = event.get("response", {})
            usage = resp.get("usage")
            if usage:
                self._final_response["usage"] = usage
            return

    def _latest_item_of_type(self, item_type: str) -> dict[str, Any] | None:
        for iid in reversed(self._item_order):
            item = self._items_by_id.get(iid)
            if item and item.get("type") == item_type:
                return item
        return None

    def final_state(self) -> dict[str, Any]:
        """Return the accumulated final response."""
        out = dict(self._final_response)
        out["output"] = [self._items_by_id[iid] for iid in self._item_order]
        return out
```

- [ ] **Step 12.3: Run streaming tests pass**

Run: `pytest tests/unit/test_streaming.py -v`
Expected: 2 PASSED.

- [ ] **Step 12.4: Commit**

```bash
git add gateway/streaming.py tests/unit/test_streaming.py
git commit -m "feat(streaming): StreamBridge — tee events and rebuild final state (#14)"
```

---

### Task 13: FastAPI app skeleton

**Spec ref:** §3
**Depends on:** Task 4 (logging/errors), Task 8, Task 9, Task 10, Task 11, Task 12
**Files:**
- Create: `gateway/api.py`
- Create: `tests/unit/test_api_health.py`

- [ ] **Step 13.1: Write failing test `tests/unit/test_api_health.py`**

```python
"""Tests for FastAPI app skeleton: health, error handlers, request id middleware."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gateway.api import build_app
from gateway.config import GatewayConfig


@pytest.fixture
def client() -> TestClient:
    app = build_app(GatewayConfig())
    return TestClient(app)


def test_healthz_returns_ok(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_response_has_request_id_header(client: TestClient) -> None:
    r = client.get("/healthz")
    assert "x-request-id" in r.headers
    assert len(r.headers["x-request-id"]) > 16


def test_request_id_is_propagated_when_provided(client: TestClient) -> None:
    r = client.get("/healthz", headers={"X-Request-Id": "client-supplied-123"})
    assert r.headers["x-request-id"] == "client-supplied-123"


def test_unhandled_gateway_error_format(client: TestClient) -> None:
    # Hit an intentionally-broken endpoint that raises a GatewayError
    r = client.get("/__test/raise-feature-not-supported")
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["type"] == "feature_not_supported"
```

Run: `pytest tests/unit/test_api_health.py -v`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 13.2: Implement `gateway/api.py` (skeleton, no /v1/responses yet)**

```python
"""FastAPI app factory + lifespan + middleware + error handlers."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from gateway.config import GatewayConfig, load_config
from gateway.errors import FeatureNotSupportedError, GatewayError
from gateway.ids import new_request_id
from gateway.logging_setup import configure_logging, get_logger


_log = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-Id") or new_request_id()
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg: GatewayConfig = app.state.config
    configure_logging(level=cfg.server.log_level, format_=cfg.server.log_format)  # type: ignore[arg-type]
    _log.info("gateway_started", port=cfg.server.port)
    yield
    _log.info("gateway_stopping")


def build_app(config: GatewayConfig) -> FastAPI:
    app = FastAPI(title="responses-gateway", lifespan=_lifespan)
    app.state.config = config
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(GatewayError)
    async def _gw_handler(request: Request, exc: GatewayError) -> JSONResponse:
        body = exc.to_response_body()
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers={"X-Request-Id": rid} if rid else {},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Test-only endpoint to verify error handler wiring
    @app.get("/__test/raise-feature-not-supported")
    async def _raise_fns() -> None:  # pragma: no cover (covered by test)
        raise FeatureNotSupportedError(
            feature="web_search", param="tools[0].type", provider="dashscope"
        )

    return app


def run() -> None:  # entrypoint registered as `responses-gateway` script
    import uvicorn

    cfg_path = os.getenv("GATEWAY_CONFIG", "config.yaml")
    cfg = load_config(cfg_path)
    app = build_app(cfg)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level=cfg.server.log_level)


# Module-level app for `uvicorn gateway.api:app --reload` (uses default config or GATEWAY_CONFIG env)
app = build_app(load_config(os.getenv("GATEWAY_CONFIG", "config.yaml")))
```

- [ ] **Step 13.3: Run API skeleton tests pass**

Run: `pytest tests/unit/test_api_health.py -v`
Expected: 4 PASSED.

- [ ] **Step 13.4: Commit**

```bash
git add gateway/api.py tests/unit/test_api_health.py
git commit -m "feat(api): FastAPI app factory, request-id middleware, error handlers"
```

---

### Task 14: POST /v1/responses (non-streaming)

**Spec ref:** §4.1 Data flow
**GitHub issues:** #1, #7
**Depends on:** Task 13
**Files:**
- Modify: `gateway/api.py` (add `/v1/responses` route + dependency wiring)
- Create: `tests/e2e/test_responses_api.py`

- [ ] **Step 14.1: Write failing test `tests/e2e/test_responses_api.py`**

```python
"""End-to-end tests for /v1/responses (non-streaming)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from gateway.api import build_app
from gateway.config import GatewayConfig
from gateway.session.models import Base
from gateway.session.store import SessionStore


@pytest.fixture
async def client() -> TestClient:
    cfg = GatewayConfig()
    cfg.storage.url = "sqlite+aiosqlite:///:memory:"
    app = build_app(cfg)
    # The app builds its store at startup; for tests we inject in-memory
    store: SessionStore = app.state.session_store
    await store.create_schema(Base.metadata)
    return TestClient(app)


def test_create_response_happy_path(client: TestClient) -> None:
    fake_resp = {
        "id": "resp_ignored",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hi!"}]}],
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_resp)):
        r = client.post(
            "/v1/responses",
            json={"input": "hi", "model": "deepseek/deepseek-chat"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["id"].startswith("resp_")
    assert body["id"] != "resp_ignored"  # we override LiteLLM's id with our own
    assert body["output"][0]["content"][0]["text"] == "Hi!"


def test_rejects_web_search_tool(client: TestClient) -> None:
    r = client.post(
        "/v1/responses",
        json={
            "input": "hi",
            "model": "deepseek/deepseek-chat",
            "tools": [{"type": "web_search"}],
        },
    )
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["type"] == "feature_not_supported"


def test_previous_response_id_chain(client: TestClient) -> None:
    fake_resp_1 = {
        "id": "ignored",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "first reply"}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    fake_resp_2 = {
        "id": "ignored",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "second reply"}]}],
        "usage": {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
    }
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(side_effect=[fake_resp_1, fake_resp_2])) as m:
        r1 = client.post(
            "/v1/responses",
            json={"input": "first", "model": "deepseek/deepseek-chat"},
        )
        assert r1.status_code == 200
        first_id = r1.json()["id"]

        r2 = client.post(
            "/v1/responses",
            json={
                "input": "second",
                "model": "deepseek/deepseek-chat",
                "previous_response_id": first_id,
            },
        )
        assert r2.status_code == 200

    # Second LiteLLM call should have received reconstructed history
    second_call_kwargs = m.await_args_list[1].kwargs
    assert "previous_response_id" not in second_call_kwargs
    second_input = second_call_kwargs["input"]
    assert isinstance(second_input, list)
    # Should contain at least 2 prior messages (user "first", assistant reply) + current "second"
    assert len(second_input) >= 3


def test_404_on_unknown_previous_response_id(client: TestClient) -> None:
    r = client.post(
        "/v1/responses",
        json={
            "input": "x",
            "model": "deepseek/deepseek-chat",
            "previous_response_id": "resp_never_created",
        },
    )
    assert r.status_code == 404
    assert r.json()["error"]["type"] == "previous_response_not_found"
```

Run: `pytest tests/e2e/test_responses_api.py -v`
Expected: FAIL — fixtures and route not wired yet.

- [ ] **Step 14.2: Wire dependencies in `gateway/api.py`**

Add to `build_app()` (replace the existing function with this expanded version):

```python
from gateway.llm import LLMRouter, provider_from_model
from gateway.session.recorder import SessionRecorder
from gateway.session.resolver import SessionResolver
from gateway.session.store import SessionStore
from gateway.storage.cold import build_cold_storage
from gateway.validator import Validator


def build_app(config: GatewayConfig) -> FastAPI:
    app = FastAPI(title="responses-gateway", lifespan=_lifespan)
    app.state.config = config
    app.add_middleware(RequestIdMiddleware)

    # Build dependencies once at app construction time
    store = SessionStore(config.storage.url)
    cold = build_cold_storage(
        enabled=config.storage.cold.enabled,
        backend=config.storage.cold.backend,
        bucket_url=config.storage.cold.bucket_url,
    )
    validator = Validator(config.reject)
    resolver = SessionResolver(store=store, cold_storage=cold)
    recorder = SessionRecorder(
        store=store,
        cold_storage=cold,
        ttl_days=config.session.default_ttl_days,
        threshold_bytes=config.storage.cold.threshold_bytes,
    )
    llm = LLMRouter(config.litellm)

    app.state.session_store = store
    app.state.validator = validator
    app.state.resolver = resolver
    app.state.recorder = recorder
    app.state.llm = llm

    @app.exception_handler(GatewayError)
    async def _gw_handler(request: Request, exc: GatewayError) -> JSONResponse:
        body = exc.to_response_body()
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers={"X-Request-Id": rid} if rid else {},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/__test/raise-feature-not-supported")
    async def _raise_fns() -> None:
        raise FeatureNotSupportedError(
            feature="web_search", param="tools[0].type", provider="dashscope"
        )

    @app.post("/v1/responses")
    async def create_response(payload: dict[str, Any]) -> dict[str, Any]:
        provider = provider_from_model(payload.get("model", ""))
        validator.validate(payload, provider=provider)

        store_flag = payload.pop("store", config.session.default_store)

        resolved = await resolver.resolve(payload, current_provider=provider)
        response = await llm.call(request=resolved.request)

        new_id = await recorder.record(
            original_request=payload,
            response_payload=response,
            provider=provider,
            model=payload.get("model", ""),
            session_id=resolved.session_id,
            parent_id=resolved.parent_id,
            store_flag=store_flag,
        )
        return {**response, "id": new_id}

    return app
```

- [ ] **Step 14.3: Run E2E tests pass**

Run: `pytest tests/e2e/test_responses_api.py -v`
Expected: 4 PASSED.

- [ ] **Step 14.4: Commit**

```bash
git add gateway/api.py tests/e2e/test_responses_api.py
git commit -m "feat(api): POST /v1/responses non-streaming with #1 reject + #7 session"
```

---

### Task 15: POST /v1/responses streaming

**Spec ref:** §4.2 Streaming
**GitHub issue:** #14
**Depends on:** Task 14
**Files:**
- Modify: `gateway/api.py` (extend route to handle `stream: true`)
- Modify: `tests/e2e/test_responses_api.py` (add streaming test)

- [ ] **Step 15.1: Add streaming test in `tests/e2e/test_responses_api.py`**

Append:

```python
async def test_streaming_response_persists_final_state(client: TestClient) -> None:
    events = [
        {"type": "response.created", "response": {"id": "ignored", "output": [], "usage": {}}},
        {"type": "response.output_item.added", "item": {"type": "message", "id": "msg_1"}},
        {"type": "response.content_part.added", "part": {"type": "output_text"}},
        {"type": "response.output_text.delta", "delta": "Hi"},
        {"type": "response.output_text.done", "text": "Hi"},
        {"type": "response.output_item.done", "item": {"type": "message", "id": "msg_1", "content": [{"type": "output_text", "text": "Hi"}]}},
        {"type": "response.completed", "response": {"id": "ignored", "output": [], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}},
    ]

    async def fake_stream():
        for e in events:
            yield e

    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_stream())):
        with client.stream(
            "POST",
            "/v1/responses",
            json={"input": "hi", "model": "deepseek/deepseek-chat", "stream": True},
        ) as r:
            assert r.status_code == 200
            chunks = list(r.iter_lines())
    # Each event becomes an SSE `data: {...}` line; should see at least 7
    data_lines = [c for c in chunks if c.startswith("data:")]
    assert len(data_lines) >= 7
```

- [ ] **Step 15.2: Implement streaming branch in `gateway/api.py`**

Replace the `create_response` body:

```python
import json as _json

from fastapi.responses import StreamingResponse

from gateway.streaming import StreamBridge


@app.post("/v1/responses")
async def create_response(request: Request, payload: dict[str, Any]) -> Any:
    provider = provider_from_model(payload.get("model", ""))
    validator.validate(payload, provider=provider)

    store_flag = payload.pop("store", config.session.default_store)
    streaming = bool(payload.get("stream", False))

    resolved = await resolver.resolve(payload, current_provider=provider)

    if not streaming:
        response = await llm.call(request=resolved.request)
        new_id = await recorder.record(
            original_request=payload,
            response_payload=response,
            provider=provider,
            model=payload.get("model", ""),
            session_id=resolved.session_id,
            parent_id=resolved.parent_id,
            store_flag=store_flag,
        )
        return {**response, "id": new_id}

    # Streaming path: tee events to client, then persist final_state
    async def _gen() -> AsyncIterator[bytes]:
        bridge = StreamBridge()
        async for event in bridge.tee(llm.stream(request=resolved.request)):
            yield f"data: {_json.dumps(event)}\n\n".encode()
        # After stream end, persist
        final = bridge.final_state()
        await recorder.record(
            original_request=payload,
            response_payload=final,
            provider=provider,
            model=payload.get("model", ""),
            session_id=resolved.session_id,
            parent_id=resolved.parent_id,
            store_flag=store_flag,
        )
        yield b"data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")
```

- [ ] **Step 15.3: Run streaming + non-streaming tests**

Run: `pytest tests/e2e/test_responses_api.py -v`
Expected: 5 PASSED (4 from Task 14 + 1 new streaming test).

- [ ] **Step 15.4: Commit**

```bash
git add gateway/api.py tests/e2e/test_responses_api.py
git commit -m "feat(api): streaming /v1/responses with persistence on stream end (#14)"
```

---

### Task 16: docker-compose for local Postgres

**Spec ref:** §8 (CI Postgres path)
**Depends on:** Task 1
**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 16.1: Create `docker-compose.yml`**

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: gateway
      POSTGRES_PASSWORD: gateway
      POSTGRES_DB: gateway_dev
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gateway -d gateway_dev"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  postgres_data:
```

- [ ] **Step 16.2: Verify Postgres comes up**

```bash
docker compose up -d postgres
docker compose ps
GATEWAY_STORAGE__URL=postgresql+asyncpg://gateway:gateway@localhost:5432/gateway_dev alembic upgrade head
docker compose down
```

Expected: `alembic upgrade head` succeeds against Postgres without errors.

- [ ] **Step 16.3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: docker-compose for local Postgres dev/integration testing"
```

---

### Task 17: Smoke test against DeepSeek

**Spec ref:** §8 Testing — Smoke
**GitHub issue:** #11 (relevant; reasoning fields verification can extend later)
**Depends on:** Task 14, 15
**Files:**
- Create: `tests/e2e/test_smoke_deepseek.py`
- Modify: `pyproject.toml` (add `markers` config)

- [ ] **Step 17.1: Add pytest marker config to `pyproject.toml`**

Append under `[tool.pytest.ini_options]`:

```toml
markers = [
    "smoke: real-network smoke tests against live providers (gated, not run by default)",
]
```

- [ ] **Step 17.2: Create `tests/e2e/test_smoke_deepseek.py`**

```python
"""Smoke test: real call against DeepSeek API. Gated; requires DEEPSEEK_API_KEY."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from gateway.api import build_app
from gateway.config import GatewayConfig
from gateway.session.models import Base
from gateway.session.store import SessionStore


pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        not os.getenv("DEEPSEEK_API_KEY"), reason="set DEEPSEEK_API_KEY to run smoke test"
    ),
]


@pytest.fixture
async def client() -> TestClient:
    cfg = GatewayConfig()
    cfg.storage.url = "sqlite+aiosqlite:///:memory:"
    app = build_app(cfg)
    store: SessionStore = app.state.session_store
    await store.create_schema(Base.metadata)
    return TestClient(app)


def test_real_deepseek_simple_call(client: TestClient) -> None:
    r = client.post(
        "/v1/responses",
        json={
            "input": "Reply with the single word: pong",
            "model": "deepseek/deepseek-chat",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"].startswith("resp_")
    assert "output" in body
    text_items = [
        c["text"]
        for item in body["output"]
        if item.get("type") == "message"
        for c in item.get("content", [])
        if c.get("type") == "output_text"
    ]
    assert text_items
    assert "pong" in "".join(text_items).lower()


def test_real_deepseek_chain_with_previous_response_id(client: TestClient) -> None:
    r1 = client.post(
        "/v1/responses",
        json={"input": "Pick a random color and remember it.", "model": "deepseek/deepseek-chat"},
    )
    assert r1.status_code == 200
    rid_1 = r1.json()["id"]

    r2 = client.post(
        "/v1/responses",
        json={
            "input": "What color did you pick? Reply with just the color.",
            "model": "deepseek/deepseek-chat",
            "previous_response_id": rid_1,
        },
    )
    assert r2.status_code == 200
    # The response should be coherent (model has access to its earlier reply)
    assert r2.json()["id"].startswith("resp_")
```

- [ ] **Step 17.3: Verify gating (skip without key)**

Run: `pytest tests/e2e/test_smoke_deepseek.py -v`
Expected: SKIPPED (DEEPSEEK_API_KEY not set).

- [ ] **Step 17.4: Verify locally if user has a key (optional)**

```bash
DEEPSEEK_API_KEY=sk-... pytest tests/e2e/test_smoke_deepseek.py -v -m smoke
```

Expected: 2 PASSED if API works.

- [ ] **Step 17.5: Commit**

```bash
git add tests/e2e/test_smoke_deepseek.py pyproject.toml
git commit -m "test: smoke test against DeepSeek (gated by DEEPSEEK_API_KEY)"
```

---

### Task 18: README polish + config example + final integration

**Spec ref:** all
**Depends on:** all previous
**Files:**
- Modify: `README.md`
- Create: `models.example.yaml`
- Run final full test suite

- [ ] **Step 18.1: Replace `README.md` with a real one**

```markdown
# Responses Gateway

> OpenAI Responses API gateway for non-OpenAI LLMs. Bridges Cursor / Codex CLI / Cline / ChatGPT Apps SDK clients to Chinese & other non-OpenAI models (Qwen / DeepSeek / Moonshot / GLM / Doubao / MiniMax / ERNIE / Hunyuan ...) via [LiteLLM](https://github.com/BerriAI/litellm).

## Quickstart

```bash
# 1. Install
uv pip install -e ".[dev,postgres,s3]"

# 2. Migrate DB (SQLite default, Postgres optional)
mkdir -p data
alembic upgrade head

# 3. Configure providers in models.yaml (see models.example.yaml)
cp models.example.yaml models.yaml
# edit models.yaml with your API keys / model names

# 4. Configure gateway (see config.example.yaml)
cp config.example.yaml config.yaml

# 5. Run
make dev
# or: uvicorn gateway.api:app --port 8080
```

## Configuration

See [`config.example.yaml`](config.example.yaml). Override any field via `GATEWAY_<SECTION>__<FIELD>` env vars.

For models, point `litellm.model_list_path` at a [LiteLLM `model_list` YAML](https://docs.litellm.ai/docs/proxy/configs).

## Auth

The gateway does not authenticate requests. Run it behind a reverse proxy (Caddy / nginx / oauth2-proxy / Cloudflare Access) that handles auth.

## What works today (v1)

- Full Responses API protocol surface for Chinese / non-OpenAI models (via LiteLLM SDK)
- `previous_response_id` stateful chains (self-managed in SQLite or Postgres)
- `store: true/false` honored
- Streaming with proper `response.output_item.added` / `.delta` / `.done` events
- `function_call` tools
- `reasoning` output items (provider-dependent)
- `file_search` tool (via LiteLLM emulation; requires LiteLLM vector store config)
- `mcp` tool pass-through

## What's explicitly rejected (with 422 error)

- `tools[*].type ∈ {web_search, web_search_preview, code_interpreter, computer_use_preview}` — see [issues #2, #4, #5](https://github.com/SimonGino/responses-gateway/issues)
- `background: true` — see issue #6
- `truncation: "auto"` — see issue #8

This is deliberate: silent failure is more dangerous than explicit rejection. See [issue #1](https://github.com/SimonGino/responses-gateway/issues/1).

## Architecture

See [`docs/superpowers/specs/2026-05-07-gateway-architecture-design.md`](docs/superpowers/specs/2026-05-07-gateway-architecture-design.md) for the full design.

## Development

```bash
make test           # full suite
make test-unit      # fast
make test-integration  # SQLite + (optionally) Postgres
make lint
make typecheck
```

## License

TBD.
```

- [ ] **Step 18.2: Create `models.example.yaml`** (LiteLLM format)

```yaml
# LiteLLM model_list — see https://docs.litellm.ai/docs/proxy/configs
# Set API keys via env vars (DEEPSEEK_API_KEY, DASHSCOPE_API_KEY, etc.)

model_list:
  - model_name: deepseek/deepseek-chat
    litellm_params:
      model: deepseek/deepseek-chat
      api_base: https://api.deepseek.com

  - model_name: deepseek/deepseek-reasoner
    litellm_params:
      model: deepseek/deepseek-reasoner
      api_base: https://api.deepseek.com

  - model_name: dashscope/qwen-max
    litellm_params:
      model: dashscope/qwen-max

  - model_name: moonshot/moonshot-v1-32k
    litellm_params:
      model: moonshot/moonshot-v1-32k

  - model_name: openrouter/zhipu/glm-4.6
    litellm_params:
      model: openrouter/zhipu/glm-4.6
```

- [ ] **Step 18.3: Run full test suite end-to-end**

```bash
ruff check gateway/ tests/
ruff format --check gateway/ tests/
mypy gateway/
pytest tests/ -v --cov=gateway --cov-report=term-missing
```

Expected: all green; coverage ≥ 80% on `gateway/` package.

- [ ] **Step 18.4: Commit + push**

```bash
git add README.md models.example.yaml
git commit -m "docs: production README + models example"
git push origin main
```

- [ ] **Step 18.5: Verify on GitHub**

Open https://github.com/SimonGino/responses-gateway. README should render. Issues #1 and #7 references should resolve.

Mark issue #7 as 🔵 In progress in `BACKLOG.md` (or close it after PR merges in actual implementation):

```bash
# In BACKLOG.md, change row 0007 status from "🟡 Tracked" to "🔵 In spec → 🟢 In progress"
# Or close the GitHub issue with: gh issue close 7 --reason completed --comment "Implemented in v1, see PR #N"
```

---

## Self-Review

### Spec coverage

| Spec § | Covered by |
|---|---|
| §1 Background & decisions | Plan opening + Task 1 (entire approach implements A2 + Intercept-and-Translate) |
| §2 Architecture overview | File structure section + Task 13 (FastAPI assembly) |
| §3 Components (9 items) | Tasks 3 (config), 4 (logging/ids/errors), 6 (store), 9 (resolver), 10 (recorder), 11 (llm), 12 (streaming), 13 (api), 7 (cold storage) |
| §4.1 Non-streaming flow | Task 14 |
| §4.2 Streaming flow | Task 15 |
| §5 Storage schema | Task 5 (model + Alembic) |
| §6 Configuration | Task 3 |
| §7 Error handling | Task 4 (errors) + Task 13 (handler) + per-component raises in Tasks 8/9/10 |
| §8 Testing strategy | Task 2 (CI), Task 16 (docker-compose), all unit/integration tests across tasks, Task 17 (smoke) |
| §9 v1 scope | Plan covers in-scope; out-of-scope items remain as backlog issues #2/#3/#4/#5/#6/#8/#9/#10 |

### Placeholder scan

- No "TBD", "TODO", or "implement later" in any task step
- Every step with code includes the actual code
- Every test step shows the actual test code
- All commit messages provided

### Type consistency

- `SessionRecord` dataclass introduced in Task 6 used consistently in Tasks 9, 10
- `ResolvedRequest` dataclass introduced in Task 9 used in Task 14
- `GatewayConfig` and sub-configs introduced in Task 3, used in Tasks 8, 11, 13
- `ColdStorage` Protocol introduced in Task 7, used in Tasks 9, 10
- `provider_from_model` helper introduced in Task 11, used in Task 14
- `StreamBridge.tee` and `final_state` signatures consistent between Task 12 (definition) and Task 15 (use)
- `Validator.validate` signature consistent between Task 8 (definition) and Task 14 (use)

### Scope check

This plan covers v1 cleanly: protocol layer (LiteLLM does the work) + previous_response_id (intercept-and-translate) + #1 graceful rejection + ops basics (config, logging, errors, CI). Out-of-scope items (web_search, code_interpreter, computer_use, native search, background mode, UI) remain in the backlog as separate issues.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-07-v1-implementation-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
