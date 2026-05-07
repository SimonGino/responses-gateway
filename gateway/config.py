"""Gateway configuration. YAML file + GATEWAY_ env override."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "GATEWAY_"
ENV_NESTED_DELIMITER = "__"


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
    fields: dict[str, Any] = Field(
        default_factory=lambda: {"background": True, "truncation": "auto"}
    )
    present_fields: list[str] = Field(
        default_factory=lambda: ["conversation", "context_management"]
    )
    workaround_url_template: str = (
        "https://github.com/SimonGino/responses-gateway/issues?q=is%3Aissue+{feature}"
    )
    # Behavior when an unsupported feature is detected:
    #   "reject" → return 422 (default; explicit failure for honest clients)
    #   "strip"  → silently drop the offending tools/fields, log a warning,
    #              and add `X-Stripped-Features` to the response header
    # Strip mode exists for non-cooperative clients (Codex / Cursor) that
    # always send a fixed toolset including `web_search`. It still surfaces
    # the issue (log + header) so it isn't a true silent-fail.
    mode: str = "reject"

    # Strip-mode only: ALSO drop tools whose `type` is not in this allow-list.
    # Default keeps the tool types LiteLLM can actually pass through to non-
    # OpenAI providers per the gap analysis §3:
    #   - "function": client-side function calling (universal)
    #   - "file_search": LiteLLM emulation via vector_stores (works on any provider)
    #   - "mcp": pass-through (provider-dependent, but LiteLLM doesn't block it)
    # Non-cooperative clients (Codex) often inject custom types like `namespace`
    # that downstream chat/completions providers reject as illegal — those still
    # get dropped. Set to `[]` to disable allow-list filtering (only the
    # explicit `tools` deny list will apply).
    strip_mode_allowed_tool_types: list[str] = Field(
        default_factory=lambda: ["function", "file_search", "mcp"]
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
        env_prefix=ENV_PREFIX,
        env_nested_delimiter=ENV_NESTED_DELIMITER,
        case_sensitive=False,
    )

    storage: StorageConfig = Field(default_factory=StorageConfig)
    litellm: LiteLLMConfig = Field(default_factory=LiteLLMConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    reject: RejectConfig = Field(default_factory=RejectConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override dict into base dict, with override taking precedence."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _parse_env_overrides() -> dict[str, Any]:
    """Extract GATEWAY_<SECTION>__<FIELD>... env vars and convert to nested dict.

    Examples:
        GATEWAY_SERVER__PORT=8080 -> {'server': {'port': 8080}}
        GATEWAY_STORAGE__COLD__ENABLED=true -> {'storage': {'cold': {'enabled': 'true'}}}

    Env vars under GATEWAY_ that *do not* contain the nested delimiter (`__`) are
    skipped. This avoids slurping unrelated GATEWAY_* env (e.g., a CI's
    GATEWAY_TEST_STORAGE) that would otherwise produce ValidationErrors against
    GatewayConfig's strict schema.

    Note: ints are coerced; bool/float are left as strings and rely on Pydantic's
    coercion when nested models are constructed.
    """
    result: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        remaining = key[len(ENV_PREFIX) :].lower()
        if ENV_NESTED_DELIMITER not in remaining:
            continue
        parts = remaining.split(ENV_NESTED_DELIMITER)

        current = result
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        try:
            current[parts[-1]] = int(value)
        except ValueError:
            current[parts[-1]] = value

    return result


def load_config(path: Path | str) -> GatewayConfig:
    """Load YAML config, then layer GATEWAY_* env overrides on top.

    Env vars take precedence over YAML values. If `path` does not exist, the
    returned config is built from defaults plus any env overrides only.

    Implementation note: pydantic-settings 2.x treats init kwargs as the
    highest-priority source (above env vars). Passing the YAML data as
    ``GatewayConfig(**yaml_data)`` would therefore *block* env overrides — the
    opposite of what we want. We work around this by parsing env vars manually
    and deep-merging them on top of YAML before instantiation. If
    pydantic-settings adds a built-in YAML source we trust, this can be
    replaced with ``settings_customise_sources`` returning
    ``(env_settings, YamlConfigSettingsSource(...), ...)``.
    """
    p = Path(path)
    yaml_data: dict[str, Any] = {}
    if p.exists():
        with p.open() as f:
            yaml_data = yaml.safe_load(f) or {}

    env_overrides = _parse_env_overrides()
    merged_data = _deep_merge(yaml_data, env_overrides)

    return GatewayConfig(**merged_data)
