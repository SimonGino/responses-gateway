"""Tests for the LiteLLM wrapper."""

from __future__ import annotations

from pathlib import Path
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

    with patch(
        "gateway.llm.litellm.aresponses", new=AsyncMock(side_effect=FakeLLMError("rate limited"))
    ):
        with pytest.raises(ProviderError) as exc:
            await router.call(request={"input": "hi", "model": "deepseek/deepseek-chat"})
    assert exc.value.status_code == 429


def test_alias_map_resolves_alias_to_litellm_string(tmp_path: Path) -> None:
    models_yaml = tmp_path / "models.yaml"
    models_yaml.write_text(
        """
model_list:
  - model_name: default-qwen
    litellm_params:
      model: dashscope/qwen-max
  - model_name: cheap
    litellm_params:
      model: deepseek/deepseek-chat
"""
    )
    cfg = LiteLLMConfig(model_list_path=str(models_yaml))
    router = LLMRouter(cfg)
    assert router.resolve_model("default-qwen") == "dashscope/qwen-max"
    assert router.resolve_model("cheap") == "deepseek/deepseek-chat"
    # Pass-through when not aliased:
    assert router.resolve_model("openai/gpt-4o") == "openai/gpt-4o"


async def test_router_uses_resolved_model_when_calling_litellm() -> None:
    """If alias resolves, litellm.aresponses must receive the resolved string, not the alias."""
    fake_response = {"id": "resp_x", "output": [], "usage": {}}
    cfg = LiteLLMConfig()
    router = LLMRouter(cfg)
    router._alias_map = {"my-alias": {"model": "deepseek/deepseek-chat"}}
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_response)) as m:
        await router.call(request={"input": "hi", "model": "my-alias"})
    assert m.await_args.kwargs["model"] == "deepseek/deepseek-chat"


async def test_router_propagates_alias_credentials_to_litellm() -> None:
    """Alias's litellm_params (api_base, api_key, ...) must be forwarded to LiteLLM,
    or downstream calls hit the wrong endpoint with no credentials."""
    fake_response = {"id": "resp_x", "output": [], "usage": {}}
    cfg = LiteLLMConfig()
    router = LLMRouter(cfg)
    router._alias_map = {
        "glm-5.1": {
            "model": "openai/glm-5.1",
            "api_base": "https://open.bigmodel.cn/api/paas/v4",
            "api_key": "zhipu-test-key",
        }
    }
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_response)) as m:
        await router.call(request={"input": "hi", "model": "glm-5.1"})
    kwargs = m.await_args.kwargs
    assert kwargs["model"] == "openai/glm-5.1"
    assert kwargs["api_base"] == "https://open.bigmodel.cn/api/paas/v4"
    assert kwargs["api_key"] == "zhipu-test-key"


async def test_alias_credentials_override_request_supplied_credentials() -> None:
    """Server-configured api_key must win over a client-supplied one (security:
    don't let unauthenticated clients inject their own credentials)."""
    fake_response = {"id": "resp_x", "output": [], "usage": {}}
    cfg = LiteLLMConfig()
    router = LLMRouter(cfg)
    router._alias_map = {
        "glm-5.1": {
            "model": "openai/glm-5.1",
            "api_key": "server-side-key",
        }
    }
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_response)) as m:
        await router.call(
            request={"input": "hi", "model": "glm-5.1", "api_key": "attacker-supplied"}
        )
    assert m.await_args.kwargs["api_key"] == "server-side-key"


async def test_router_call_coerces_pydantic_response_to_dict() -> None:
    """Non-streaming path: newer litellm returns a Pydantic ``ResponsesAPIResponse``
    rather than a dict. Downstream code (api.create_response) does
    ``response['id'] = ...`` so the wrapper must coerce."""
    from dataclasses import dataclass, field

    @dataclass
    class FakeResp:
        id: str = "resp_litellm"
        output: list[Any] = field(default_factory=list)
        usage: dict[str, Any] = field(default_factory=dict)

        def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
            return {"id": self.id, "output": self.output, "usage": self.usage}

    router = LLMRouter(LiteLLMConfig())
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=FakeResp())):
        result = await router.call(request={"input": "hi", "model": "deepseek/x"})
    assert isinstance(result, dict)
    result["id"] = "resp_gateway"  # must be mutable like a dict
    assert result["id"] == "resp_gateway"


async def test_router_stream_coerces_pydantic_events_to_dicts() -> None:
    """LiteLLM yields Pydantic ResponseCreatedEvent etc. on streaming; the gateway
    must convert them to dicts so the SSE JSON encoder + StreamBridge can use them."""
    from dataclasses import dataclass

    @dataclass
    class FakeEventV2:
        """Stand-in with a `model_dump` method (mirrors Pydantic v2's API)."""

        type: str
        delta: str | None = None
        _resp_id: str | None = None

        def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
            out: dict[str, Any] = {"type": self.type}
            if self._resp_id is not None:
                out["response"] = {"id": self._resp_id, "output": []}
            if self.delta is not None:
                out["delta"] = self.delta
            return out

    events_in = [
        FakeEventV2(type="response.created", _resp_id="x"),
        FakeEventV2(type="response.output_text.delta", delta="hi"),
    ]

    async def fake_iter() -> Any:
        for e in events_in:
            yield e

    cfg = LiteLLMConfig()
    router = LLMRouter(cfg)
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_iter())):
        events_out = [
            e async for e in router.stream(request={"input": "hi", "model": "deepseek/x"})
        ]
    assert all(isinstance(e, dict) for e in events_out)
    assert events_out[0]["type"] == "response.created"
    assert events_out[0]["response"]["id"] == "x"
    assert events_out[1]["delta"] == "hi"


def test_load_alias_map_preserves_full_litellm_params(tmp_path: Path) -> None:
    """Loader must capture api_base / api_key, not just the model string."""
    models_yaml = tmp_path / "models.yaml"
    models_yaml.write_text(
        """
model_list:
  - model_name: glm-5.1
    litellm_params:
      model: openai/glm-5.1
      api_base: https://open.bigmodel.cn/api/paas/v4
      api_key: zhipu-test-key
      extra_body:
        thinking:
          type: enabled
"""
    )
    cfg = LiteLLMConfig(model_list_path=str(models_yaml))
    router = LLMRouter(cfg)
    params = router._alias_map["glm-5.1"]
    assert params["model"] == "openai/glm-5.1"
    assert params["api_base"] == "https://open.bigmodel.cn/api/paas/v4"
    assert params["api_key"] == "zhipu-test-key"
    assert params["extra_body"] == {"thinking": {"type": "enabled"}}
