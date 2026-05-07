"""Cold storage backend for large session payloads. Optional and pluggable."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Protocol

from gateway.errors import ColdStorageUnavailableError


class ColdStorage(Protocol):
    """Backend protocol for offloaded payload storage. All ops are async."""

    async def put(self, payload: dict[str, Any]) -> str:
        """Store payload, return opaque object key."""
        ...

    async def get(self, key: str) -> dict[str, Any]:
        """Retrieve payload by key. Raises ColdStorageUnavailableError on failure."""
        ...


class InMemoryColdStorage:
    """In-memory backend for tests and single-process dev."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def put_sync(self, payload: dict[str, Any]) -> str:
        key = uuid.uuid4().hex
        self._data[key] = json.dumps(payload).encode()
        return key

    def get_sync(self, key: str) -> dict[str, Any]:
        if key not in self._data:
            raise ColdStorageUnavailableError(f"cold storage key not found: {key}")
        result: dict[str, Any] = json.loads(self._data[key])
        return result

    async def put(self, payload: dict[str, Any]) -> str:
        return await asyncio.to_thread(self.put_sync, payload)

    async def get(self, key: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_sync, key)


class S3ColdStorage:
    """S3-backed cold storage. Requires `aioboto3` (install extra `s3`).

    Only stores JSON-serializable payloads. `bucket_url` format: `s3://bucket-name/optional-prefix`.
    """

    def __init__(self, bucket_url: str) -> None:
        if not bucket_url.startswith("s3://"):
            raise ValueError(f"Invalid S3 bucket URL: {bucket_url}")
        rest = bucket_url[5:]
        parts = rest.split("/", 1)
        self._bucket = parts[0]
        self._prefix = parts[1].rstrip("/") + "/" if len(parts) == 2 and parts[1] else ""

    async def put(self, payload: dict[str, Any]) -> str:
        import aioboto3  # type: ignore[import-untyped]

        key = f"{self._prefix}{uuid.uuid4().hex}.json"
        try:
            async with aioboto3.Session().client("s3") as s3:
                await s3.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=json.dumps(payload).encode(),
                    ContentType="application/json",
                )
            return key
        except Exception as exc:
            raise ColdStorageUnavailableError(f"S3 put failed: {exc}") from exc

    async def get(self, key: str) -> dict[str, Any]:
        import aioboto3  # type: ignore[import-untyped]

        try:
            async with aioboto3.Session().client("s3") as s3:
                resp = await s3.get_object(Bucket=self._bucket, Key=key)
                body = await resp["Body"].read()
                result: dict[str, Any] = json.loads(body)
                return result
        except Exception as exc:
            raise ColdStorageUnavailableError(f"S3 get failed: {exc}") from exc


def build_cold_storage(
    *, enabled: bool, backend: str, bucket_url: str | None
) -> ColdStorage | None:
    """Factory: returns None if disabled."""
    if not enabled:
        return None
    if backend == "inmem":
        return InMemoryColdStorage()
    if backend == "s3":
        if not bucket_url:
            raise ValueError("cold.bucket_url required when backend=s3")
        return S3ColdStorage(bucket_url)
    raise ValueError(f"unknown cold storage backend: {backend}")
