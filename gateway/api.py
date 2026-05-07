"""FastAPI app factory + lifespan + middleware + error handlers + /v1/responses."""

from __future__ import annotations

import json as _json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from gateway.config import GatewayConfig, load_config
from gateway.errors import FeatureNotSupportedError, GatewayError
from gateway.ids import new_request_id, new_response_id
from gateway.llm import LLMRouter, provider_from_model
from gateway.logging_setup import configure_logging, get_logger
from gateway.session.recorder import SessionRecorder
from gateway.session.resolver import SessionResolver
from gateway.session.store import SessionStore
from gateway.storage.cold import build_cold_storage
from gateway.streaming import StreamBridge
from gateway.validator import Validator

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

    # Build dependencies once at app construction time
    store = SessionStore(config.storage.url)
    cold = build_cold_storage(
        enabled=config.storage.cold.enabled,
        backend=config.storage.cold.backend,
        bucket_url=config.storage.cold.bucket_url,
    )
    validator = Validator(config.reject)
    resolver = SessionResolver(store=store, cold_storage=cold)
    recorder = SessionRecorder(
        store=store,
        cold_storage=cold,
        ttl_days=config.session.default_ttl_days,
        threshold_bytes=config.storage.cold.threshold_bytes,
    )
    llm = LLMRouter(config.litellm)

    app.state.session_store = store
    app.state.validator = validator
    app.state.resolver = resolver
    app.state.recorder = recorder
    app.state.llm = llm

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

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        """OpenAI-compatible models list. Returns alias names from models.yaml.

        Many clients (Cursor / Codex / ChatGPT Apps) probe this endpoint on
        startup to discover available models. Returns 200 with empty data[]
        if no aliases are configured rather than 404.
        """
        aliases = llm.list_aliases()
        return {
            "object": "list",
            "data": [
                {
                    "id": name,
                    "object": "model",
                    "owned_by": provider_from_model(litellm_str),
                }
                for name, litellm_str in aliases.items()
            ],
        }

    @app.get("/__test/raise-feature-not-supported")
    async def _raise_fns() -> None:  # pragma: no cover
        raise FeatureNotSupportedError(
            feature="web_search", param="tools[0].type", provider="dashscope"
        )

    @app.post("/v1/responses")
    async def create_response(request: Request, payload: dict[str, Any]) -> Any:
        provider = provider_from_model(payload.get("model", ""))
        validator.validate(payload, provider=provider)

        store_flag = payload.pop("store", config.session.default_store)
        streaming = bool(payload.get("stream", False))

        # Generate gateway-side id BEFORE calling LiteLLM. Streaming needs
        # this so we can rewrite response.id in lifecycle events from the
        # very first chunk, not after.
        new_id = new_response_id()

        resolved = await resolver.resolve(payload, current_provider=provider)

        if not streaming:
            response = await llm.call(request=resolved.request)
            response["id"] = new_id
            await recorder.record(
                response_id=new_id,
                original_request=payload,
                response_payload=response,
                provider=provider,
                model=payload.get("model", ""),
                session_id=resolved.session_id,
                parent_id=resolved.parent_id,
                store_flag=store_flag,
            )
            return response

        # Streaming path: tee events to client, then persist final state on close.
        # Once the SSE stream starts (200 + text/event-stream sent), we cannot
        # change to an HTTP error response — so any GatewayError raised mid-stream
        # is emitted as a `response.failed` event followed by `[DONE]` so OpenAI
        # clients understand the stream terminated cleanly.
        async def _gen() -> AsyncIterator[bytes]:
            bridge = StreamBridge(rewrite_id=new_id)
            try:
                async for event in bridge.tee(llm.stream(request=resolved.request)):
                    yield f"data: {_json.dumps(event)}\n\n".encode()
                final = bridge.final_state()
                final["id"] = new_id
                await recorder.record(
                    response_id=new_id,
                    original_request=payload,
                    response_payload=final,
                    provider=provider,
                    model=payload.get("model", ""),
                    session_id=resolved.session_id,
                    parent_id=resolved.parent_id,
                    store_flag=store_flag,
                )
            except GatewayError as exc:
                _log.warn(
                    "stream_error_emitting_response_failed",
                    response_id=new_id,
                    error_type=exc.error_type,
                    status_code=exc.status_code,
                )
                error_body = exc.to_response_body()["error"]
                failed_event = {
                    "type": "response.failed",
                    "response": {
                        "id": new_id,
                        "status": "failed",
                        "error": error_body,
                    },
                }
                yield f"data: {_json.dumps(failed_event)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(_gen(), media_type="text/event-stream")

    return app


def run() -> None:
    import uvicorn

    cfg_path = os.getenv("GATEWAY_CONFIG", "config.yaml")
    cfg = load_config(cfg_path)
    app = build_app(cfg)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level=cfg.server.log_level)


# Module-level app for `uvicorn gateway.api:app --reload`
app = build_app(load_config(os.getenv("GATEWAY_CONFIG", "config.yaml")))
