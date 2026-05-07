"""Tests for FastAPI app skeleton: health, error handlers, request id middleware."""

from __future__ import annotations

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
