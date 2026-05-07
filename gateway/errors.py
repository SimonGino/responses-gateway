"""Gateway error types. Each carries an HTTP status code and an OpenAI-shaped error body."""

from __future__ import annotations

from typing import Any


class GatewayError(Exception):
    status_code: int = 500
    error_type: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, param: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.param = param

    def to_response_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {
                "type": self.error_type,
                "message": self.message,
            }
        }
        if self.code:
            body["error"]["code"] = self.code
        if self.param:
            body["error"]["param"] = self.param
        return body


class FeatureNotSupportedError(GatewayError):
    status_code = 422
    error_type = "feature_not_supported"

    def __init__(
        self,
        *,
        feature: str,
        param: str,
        provider: str | None = None,
        workaround_url: str | None = None,
    ) -> None:
        msg = f"{feature} is not yet supported"
        if provider:
            msg += f" for provider '{provider}'"
        if workaround_url:
            msg += f". Track at {workaround_url}"
        super().__init__(msg, code="feature_not_supported", param=param)
        self.feature = feature
        self.provider = provider


class PreviousResponseNotFoundError(GatewayError):
    status_code = 404
    error_type = "previous_response_not_found"

    def __init__(self, *, previous_response_id: str) -> None:
        super().__init__(
            f"previous_response_id '{previous_response_id}' not found",
            param="previous_response_id",
        )


class PreviousResponseExpiredError(GatewayError):
    status_code = 410
    error_type = "previous_response_expired"

    def __init__(self, *, previous_response_id: str) -> None:
        super().__init__(
            f"previous_response_id '{previous_response_id}' has expired",
            param="previous_response_id",
        )


class PreviousResponseProviderMismatchError(GatewayError):
    status_code = 409
    error_type = "previous_response_provider_mismatch"

    def __init__(self, *, parent_provider: str, current_provider: str) -> None:
        super().__init__(
            f"chained response was for provider '{parent_provider}' but current request "
            f"targets provider '{current_provider}'; cannot reuse session across providers",
            param="model",
        )


class ColdStorageUnavailableError(GatewayError):
    status_code = 503
    error_type = "cold_storage_unavailable"


class StorageUnavailableError(GatewayError):
    status_code = 503
    error_type = "storage_unavailable"


class ProviderError(GatewayError):
    """Wraps a LiteLLM/provider failure for client visibility."""

    error_type = "provider_error"

    def __init__(
        self, message: str, *, status_code: int, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}

    def to_response_body(self) -> dict[str, Any]:
        body = super().to_response_body()
        if self.details:
            body["error"]["details"] = self.details
        return body
