"""Tests for the LiteLLM wrapper."""

from __future__ import annotations

from pathlib import Path
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
    router._alias_map = {"my-alias": "deepseek/deepseek-chat"}
    with patch("gateway.llm.litellm.aresponses", new=AsyncMock(return_value=fake_response)) as m:
        await router.call(request={"input": "hi", "model": "my-alias"})
    assert m.await_args.kwargs["model"] == "deepseek/deepseek-chat"
