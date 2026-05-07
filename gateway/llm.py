"""Thin wrapper around `litellm.aresponses`. The only LLM dependency in the gateway.

Reads a LiteLLM-format `model_list` YAML purely as an alias map: a request
asking for `default-qwen` will route to `dashscope/qwen-max` (etc.). Does NOT
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


def _load_alias_map(model_list_path: str | None) -> dict[str, str]:
    """Build {request_name: litellm_string} from a LiteLLM model_list yaml.

    Each entry's `model_name` is the alias clients use; its `litellm_params.model`
    is the actual LiteLLM-recognized provider/model string.
    """
    if not model_list_path:
        return {}
    p = Path(model_list_path)
    if not p.exists():
        return {}
    with p.open() as f:
        cfg = yaml.safe_load(f) or {}
    entries = cfg.get("model_list") or []
    aliases: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("model_name")
        params = entry.get("litellm_params") or {}
        litellm_model = params.get("model") if isinstance(params, dict) else None
        if name and litellm_model:
            aliases[str(name)] = str(litellm_model)
    return aliases


class LLMRouter:
    def __init__(self, config: LiteLLMConfig) -> None:
        self._cfg = config
        self._alias_map = _load_alias_map(config.model_list_path)

    def resolve_model(self, requested: str) -> str:
        """Map alias → real LiteLLM model string. Pass-through if not aliased."""
        return self._alias_map.get(requested, requested)

    def list_aliases(self) -> dict[str, str]:
        """Public introspection for /v1/models — return a copy of the alias map."""
        return dict(self._alias_map)

    async def call(self, *, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return cast(
                dict[str, Any],
                await litellm.aresponses(
                    **{**request, "model": self.resolve_model(request.get("model", ""))},
                    timeout=self._cfg.request_timeout,
                    num_retries=self._cfg.num_retries,
                ),
            )
        except Exception as exc:
            raise self._wrap(exc) from exc

    async def stream(self, *, request: dict[str, Any]) -> AsyncIterator[Any]:
        try:
            # Strip `stream` from the caller's request dict before unpacking:
            # this method always adds stream=True explicitly, so leaving it in
            # the spread would produce a "multiple values for keyword argument" error.
            request_without_stream = {k: v for k, v in request.items() if k != "stream"}
            iterator = await litellm.aresponses(
                **{**request_without_stream, "model": self.resolve_model(request.get("model", ""))},
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
        details: dict[str, Any] = {}
        for attr in ("type", "code", "param"):
            v = getattr(exc, attr, None)
            if v is not None:
                details[attr] = v
        return ProviderError(message=str(exc), status_code=int(status), details=details)
