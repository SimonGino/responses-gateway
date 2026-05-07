"""Tests for FastAPI app skeleton: health, error handlers, request id middleware."""

from __future__ import annotations

from pathlib import Path

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


def test_list_models_returns_200_with_empty_data(client: TestClient) -> None:
    """Default config has no model_list_path so data[] is empty — but the
    endpoint must exist (status 200, not 404), or clients fail to connect."""
    r = client.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert body["data"] == []


def test_list_models_with_alias_map(tmp_path: Path) -> None:
    """When models.yaml is provided, /v1/models surfaces each alias with its
    inferred provider (from the litellm string prefix)."""
    models_yaml = tmp_path / "models.yaml"
    models_yaml.write_text(
        """
model_list:
  - model_name: my-default-qwen
    litellm_params:
      model: dashscope/qwen-max
  - model_name: my-cheap
    litellm_params:
      model: deepseek/deepseek-chat
"""
    )
    cfg = GatewayConfig()
    cfg.litellm.model_list_path = str(models_yaml)
    app = build_app(cfg)
    c = TestClient(app)
    r = c.get("/v1/models")
    body = r.json()
    ids = {d["id"]: d["owned_by"] for d in body["data"]}
    assert ids == {
        "my-default-qwen": "dashscope",
        "my-cheap": "deepseek",
    }
    for entry in body["data"]:
        assert entry["object"] == "model"
