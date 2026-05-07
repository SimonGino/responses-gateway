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
