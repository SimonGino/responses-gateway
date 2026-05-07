"""FastAPI app factory + lifespan + middleware + error handlers."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from gateway.config import GatewayConfig, load_config
from gateway.errors import FeatureNotSupportedError, GatewayError
from gateway.ids import new_request_id
from gateway.logging_setup import configure_logging, get_logger

_log = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-Id") or new_request_id()
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg: GatewayConfig = app.state.config
    configure_logging(level=cfg.server.log_level, format_=cfg.server.log_format)  # type: ignore[arg-type]
    _log.info("gateway_started", port=cfg.server.port)
    yield
    _log.info("gateway_stopping")


def build_app(config: GatewayConfig) -> FastAPI:
    app = FastAPI(title="responses-gateway", lifespan=_lifespan)
    app.state.config = config
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(GatewayError)
    async def _gw_handler(request: Request, exc: GatewayError) -> JSONResponse:
        body = exc.to_response_body()
        rid = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers={"X-Request-Id": rid} if rid else {},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Test-only endpoint to verify error handler wiring
    @app.get("/__test/raise-feature-not-supported")
    async def _raise_fns() -> None:  # pragma: no cover (covered by test)
        raise FeatureNotSupportedError(
            feature="web_search", param="tools[0].type", provider="dashscope"
        )

    return app


def run() -> None:  # entrypoint registered as `responses-gateway` script
    import uvicorn

    cfg_path = os.getenv("GATEWAY_CONFIG", "config.yaml")
    cfg = load_config(cfg_path)
    app = build_app(cfg)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level=cfg.server.log_level)


# Module-level app for `uvicorn gateway.api:app --reload`
app = build_app(load_config(os.getenv("GATEWAY_CONFIG", "config.yaml")))
