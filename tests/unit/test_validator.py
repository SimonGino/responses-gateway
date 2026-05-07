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


# ---------- Strip mode (mode="strip") ----------


@pytest.fixture
def strip_validator() -> Validator:
    return Validator(RejectConfig(mode="strip"))


def test_strip_mode_drops_unsupported_tool_in_place(strip_validator: Validator) -> None:
    request = {
        "input": "hi",
        "tools": [
            {"type": "function", "name": "f"},
            {"type": "web_search"},
            {"type": "function", "name": "g"},
        ],
    }
    stripped = strip_validator.validate(request)
    assert stripped == [("web_search", "tools[1].type")]
    # Surviving tools preserve original order; web_search is gone.
    assert [t.get("type") or t.get("name") for t in request["tools"]] == ["function", "function"]


def test_strip_mode_drops_multiple_unsupported_tools(strip_validator: Validator) -> None:
    request = {
        "input": "hi",
        "tools": [
            {"type": "web_search"},
            {"type": "function", "name": "f"},
            {"type": "code_interpreter"},
            {"type": "function", "name": "g"},
            {"type": "computer_use_preview"},
        ],
    }
    stripped = strip_validator.validate(request)
    assert {f for f, _ in stripped} == {"web_search", "code_interpreter", "computer_use_preview"}
    assert all(t.get("type") == "function" for t in request["tools"])


def test_strip_mode_drops_offending_field(strip_validator: Validator) -> None:
    request = {"input": "hi", "background": True}
    stripped = strip_validator.validate(request)
    assert stripped == [("background", "background")]
    assert "background" not in request


def test_strip_mode_drops_present_only_field(strip_validator: Validator) -> None:
    request = {"input": "hi", "conversation": "conv_xxx"}
    stripped = strip_validator.validate(request)
    assert stripped == [("conversation", "conversation")]
    assert "conversation" not in request


def test_strip_mode_returns_empty_list_when_request_clean(strip_validator: Validator) -> None:
    request = {"input": "hi", "model": "deepseek/deepseek-chat"}
    stripped = strip_validator.validate(request)
    assert stripped == []


def test_strip_mode_removes_tools_key_when_all_dropped(strip_validator: Validator) -> None:
    """If stripping empties the tools list, drop the key entirely — some
    providers reject explicit empty tool arrays."""
    request = {"input": "hi", "tools": [{"type": "web_search"}]}
    strip_validator.validate(request)
    assert "tools" not in request


def test_default_mode_is_reject() -> None:
    """Default config should still raise (preserves backwards-compat for v1 spec)."""
    cfg = RejectConfig()
    assert cfg.mode == "reject"
    v = Validator(cfg)
    with pytest.raises(FeatureNotSupportedError):
        v.validate({"input": "hi", "tools": [{"type": "web_search"}]})


def test_strip_mode_drops_non_function_tool_types(strip_validator: Validator) -> None:
    """Default allow-list is ['function']; namespace/custom types must be stripped
    even though they aren't in the explicit deny list."""
    request = {
        "input": "hi",
        "tools": [
            {"type": "function", "name": "f"},
            {"type": "namespace", "name": "Codex_Namespace_1"},  # ← Codex-specific
            {"type": "function", "name": "g"},
            {"type": "namespace", "name": "Codex_Namespace_2"},
        ],
    }
    stripped = strip_validator.validate(request)
    assert {f for f, _ in stripped} == {"namespace"}
    assert all(t.get("type") == "function" for t in request["tools"])


def test_strip_mode_allow_list_can_be_extended() -> None:
    """User can add 'mcp' or other types to the allow list via config."""
    cfg = RejectConfig(mode="strip", strip_mode_allowed_tool_types=["function", "mcp"])
    v = Validator(cfg)
    request = {
        "input": "hi",
        "tools": [
            {"type": "function"},
            {"type": "mcp"},
            {"type": "namespace"},
        ],
    }
    v.validate(request)
    surviving = [t["type"] for t in request["tools"]]
    assert surviving == ["function", "mcp"]


def test_strip_mode_with_empty_allow_list_skips_unknown_filter() -> None:
    """Setting allow list to [] disables allow-list filtering — only the explicit
    deny list applies."""
    cfg = RejectConfig(mode="strip", strip_mode_allowed_tool_types=[])
    v = Validator(cfg)
    request = {
        "input": "hi",
        "tools": [
            {"type": "function"},
            {"type": "namespace"},  # not in deny list, allow list disabled → kept
        ],
    }
    v.validate(request)
    surviving = [t["type"] for t in request["tools"]]
    assert surviving == ["function", "namespace"]


def test_reject_mode_does_not_apply_allow_list() -> None:
    """The allow-list filter is strip-mode only — reject mode lets non-deny-listed
    tool types through (even unusual ones), preserving the spec contract that
    reject mode only rejects items explicitly in the deny config."""
    cfg = RejectConfig(mode="reject", strip_mode_allowed_tool_types=["function"])
    v = Validator(cfg)
    # `namespace` is not in the deny list and we're in reject mode, so it should
    # pass through (not raise).
    v.validate({"input": "hi", "tools": [{"type": "namespace"}]})
