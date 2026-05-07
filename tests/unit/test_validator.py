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


# Spec amendment: presence-based rejection for OpenAI's newer fields
# that are mutually exclusive with previous_response_id


def test_rejects_conversation_field_presence(validator: Validator) -> None:
    with pytest.raises(FeatureNotSupportedError) as exc:
        validator.validate({"input": "hi", "conversation": "conv_123"})
    assert exc.value.feature == "conversation"


def test_rejects_context_management_presence(validator: Validator) -> None:
    with pytest.raises(FeatureNotSupportedError) as exc:
        validator.validate({"input": "hi", "context_management": {"strategy": "summarize"}})
    assert exc.value.feature == "context_management"


def test_allows_request_without_present_fields(validator: Validator) -> None:
    # Plain request should not trip presence rejection
    validator.validate({"input": "hi", "model": "deepseek/deepseek-chat"})
