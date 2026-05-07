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


def test_three_level_nested_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`GATEWAY_STORAGE__COLD__ENABLED=true` must override yaml at depth 3."""
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("storage:\n  cold:\n    enabled: false\n")
    monkeypatch.setenv("GATEWAY_STORAGE__COLD__ENABLED", "true")
    cfg = load_config(yaml_path)
    assert cfg.storage.cold.enabled is True


def test_partial_yaml_only_overrides_specified_sections(tmp_path: Path) -> None:
    """A YAML file with only one section should leave other sections at defaults."""
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("server:\n  port: 7777\n")
    cfg = load_config(yaml_path)
    assert cfg.server.port == 7777
    # Other sections at defaults
    assert cfg.session.default_ttl_days == 30
    assert cfg.storage.url.startswith("sqlite+aiosqlite")


def test_unrelated_gateway_env_vars_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GATEWAY_* env vars without `__` delimiter (e.g., GATEWAY_TEST_FOO from CI) must not
    leak into config parsing — they would otherwise be rejected as extra fields."""
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("")
    monkeypatch.setenv("GATEWAY_TEST_STORAGE", "sqlite")
    monkeypatch.setenv("GATEWAY_TEST_POSTGRES_URL", "postgresql://x")
    cfg = load_config(yaml_path)
    assert cfg.server.port == 8080  # defaults still load cleanly
