"""Tests for gateway error types."""

from __future__ import annotations

from gateway.errors import (
    ColdStorageUnavailableError,
    FeatureNotSupportedError,
    GatewayError,
    PreviousResponseExpiredError,
    PreviousResponseNotFoundError,
    PreviousResponseProviderMismatchError,
    StorageUnavailableError,
)


def test_feature_not_supported_has_status_422() -> None:
    err = FeatureNotSupportedError(
        feature="web_search", param="tools[0].type", provider="dashscope"
    )
    assert err.status_code == 422
    assert err.error_type == "feature_not_supported"
    body = err.to_response_body()
    assert body["error"]["type"] == "feature_not_supported"
    assert body["error"]["param"] == "tools[0].type"
    assert "web_search" in body["error"]["message"]


def test_previous_response_not_found_is_404() -> None:
    err = PreviousResponseNotFoundError(previous_response_id="resp_xxx")
    assert err.status_code == 404
    assert err.error_type == "previous_response_not_found"


def test_previous_response_expired_is_410() -> None:
    err = PreviousResponseExpiredError(previous_response_id="resp_xxx")
    assert err.status_code == 410


def test_provider_mismatch_is_409() -> None:
    err = PreviousResponseProviderMismatchError(
        parent_provider="dashscope", current_provider="deepseek"
    )
    assert err.status_code == 409


def test_storage_unavailable_is_503() -> None:
    err = StorageUnavailableError("connection refused")
    assert err.status_code == 503


def test_cold_storage_read_unavailable_is_503() -> None:
    err = ColdStorageUnavailableError("S3 timeout")
    assert err.status_code == 503


def test_gateway_error_is_base() -> None:
    assert issubclass(FeatureNotSupportedError, GatewayError)
