"""Thin wrapper around `litellm.aresponses`. The only LLM dependency in the gateway.

Reads a LiteLLM-format `model_list` YAML as a per-alias `litellm_params` map.
A request asking for `glm-5.1` resolves to the alias entry's *full* params
(model string + api_base + api_key + any other litellm_params field). Does NOT
instantiate `litellm.Router` — fallback chains, load balancing, cooldowns,
virtual keys are out of scope for v1. Multi-deployment routing is delegated
to whatever load balancer sits in front of the gateway.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import litellm
import yaml

from gateway.config import LiteLLMConfig
from gateway.errors import ProviderError


def provider_from_model(model: str) -> str:
    """Extract provider prefix. `dashscope/qwen-max` → `dashscope`. No slash → 'openai'."""
    if "/" not in model:
        return "openai"
    return model.split("/", 1)[0]


def _event_to_dict(event: Any) -> dict[str, Any]:
    """Coerce a streaming event from LiteLLM into a plain JSON-able dict.

    LiteLLM's `aresponses(stream=True)` yields Pydantic event models
    (`ResponseCreatedEvent`, `ResponseOutputTextDeltaEvent`, ...) which
    `json.dumps` cannot serialize directly. StreamBridge and the SSE
    serializer both assume `dict[str, Any]`, so we normalize at this
    boundary.
    """
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):  # Pydantic v2
        return cast(dict[str, Any], event.model_dump(exclude_none=True))
    if hasattr(event, "dict"):  # Pydantic v1 fallback
        return cast(dict[str, Any], event.dict(exclude_none=True))
    return {"type": "unknown", "raw": str(event)}


def _load_alias_map(model_list_path: str | None) -> dict[str, dict[str, Any]]:
    """Build {request_name: litellm_params_dict} from a LiteLLM model_list yaml.

    Each entry's `model_name` is the alias clients use. The full
    `litellm_params` dict is preserved — including `api_base`, `api_key`,
    `extra_body`, etc. — and spread as kwargs into `litellm.aresponses` at
    call time. Without this, alias-time credentials would be lost and
    LiteLLM would fall back to env-var auth (or no auth at all).
    """
    if not model_list_path:
        return {}
    p = Path(model_list_path)
    if not p.exists():
        return {}
    with p.open() as f:
        cfg = yaml.safe_load(f) or {}
    entries = cfg.get("model_list") or []
    aliases: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("model_name")
        params = entry.get("litellm_params") or {}
        if name and isinstance(params, dict) and params.get("model"):
            aliases[str(name)] = dict(params)
    return aliases


class LLMRouter:
    def __init__(self, config: LiteLLMConfig) -> None:
        self._cfg = config
        self._alias_map = _load_alias_map(config.model_list_path)

    def resolve_model(self, requested: str) -> str:
        """Return the litellm model string for an alias, else the input unchanged."""
        params = self._alias_map.get(requested)
        if params is None:
            return requested
        return str(params.get("model", requested))

    def list_aliases(self) -> dict[str, str]:
        """Public introspection for /v1/models — return alias_name → model_string."""
        return {name: str(p.get("model", "")) for name, p in self._alias_map.items()}

    def _resolve_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Apply alias resolution: replace model and merge api_base/api_key/etc.

        The alias's `litellm_params` win over request fields on overlap. This
        means a server-configured `api_key` cannot be overridden by a client-
        supplied one — important so an unauthenticated downstream client can't
        inject its own credentials onto the gateway's outbound call.
        """
        requested = request.get("model", "")
        params = self._alias_map.get(requested)
        if params is None:
            return request
        return {**request, **params}

    async def call(self, *, request: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await litellm.aresponses(
                **self._resolve_request(request),
                timeout=self._cfg.request_timeout,
                num_retries=self._cfg.num_retries,
            )
            return _event_to_dict(response)
        except Exception as exc:
            raise self._wrap(exc) from exc

    async def stream(self, *, request: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        try:
            # Strip `stream` from the caller's request dict before unpacking:
            # this method always adds stream=True explicitly, so leaving it in
            # the spread would produce a "multiple values for keyword argument" error.
            request_without_stream = {k: v for k, v in request.items() if k != "stream"}
            iterator = await litellm.aresponses(
                **self._resolve_request(request_without_stream),
                stream=True,
                timeout=self._cfg.request_timeout,
                num_retries=self._cfg.num_retries,
            )
            async for event in iterator:
                yield _event_to_dict(event)
        except Exception as exc:
            raise self._wrap(exc) from exc

    @staticmethod
    def _wrap(exc: Exception) -> ProviderError:
        status = getattr(exc, "status_code", 502)
        details: dict[str, Any] = {}
        for attr in ("type", "code", "param"):
            v = getattr(exc, attr, None)
            if v is not None:
                details[attr] = v
        return ProviderError(message=str(exc), status_code=int(status), details=details)
