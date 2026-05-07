"""Tests for the in-memory ColdStorage implementation (used in tests + dev)."""

from __future__ import annotations

import pytest

from gateway.errors import ColdStorageUnavailableError
from gateway.storage.cold import (
    ColdStorage,
    InMemoryColdStorage,
    S3ColdStorage,
    build_cold_storage,
)


def test_inmem_storage_roundtrip() -> None:
    cs = InMemoryColdStorage()
    payload = {"input": [{"role": "user", "content": "hi"}], "output": [{"type": "message"}]}
    key = cs.put_sync(payload)
    fetched = cs.get_sync(key)
    assert fetched == payload


def test_inmem_get_missing_raises() -> None:
    cs = InMemoryColdStorage()
    with pytest.raises(ColdStorageUnavailableError):
        cs.get_sync("nonexistent-key")


async def test_inmem_storage_async_api() -> None:
    cs: ColdStorage = InMemoryColdStorage()
    key = await cs.put({"a": 1})
    fetched = await cs.get(key)
    assert fetched == {"a": 1}


# ---------- build_cold_storage factory ----------


def test_build_cold_storage_disabled_returns_none() -> None:
    assert build_cold_storage(enabled=False, backend="s3", bucket_url=None) is None
    assert build_cold_storage(enabled=False, backend="inmem", bucket_url=None) is None


def test_build_cold_storage_inmem_returns_instance() -> None:
    cs = build_cold_storage(enabled=True, backend="inmem", bucket_url=None)
    assert isinstance(cs, InMemoryColdStorage)


def test_build_cold_storage_s3_requires_bucket_url() -> None:
    with pytest.raises(ValueError, match="bucket_url"):
        build_cold_storage(enabled=True, backend="s3", bucket_url=None)


def test_build_cold_storage_unknown_backend_raises() -> None:
    with pytest.raises(ValueError, match="unknown cold storage backend"):
        build_cold_storage(enabled=True, backend="floppy_disk", bucket_url=None)


# ---------- S3ColdStorage URL parsing ----------


def test_s3_url_bucket_only() -> None:
    cs = S3ColdStorage("s3://my-bucket")
    assert cs._bucket == "my-bucket"
    assert cs._prefix == ""


def test_s3_url_bucket_with_trailing_slash() -> None:
    cs = S3ColdStorage("s3://my-bucket/")
    assert cs._bucket == "my-bucket"
    assert cs._prefix == ""


def test_s3_url_bucket_with_prefix() -> None:
    cs = S3ColdStorage("s3://my-bucket/sessions")
    assert cs._bucket == "my-bucket"
    assert cs._prefix == "sessions/"


def test_s3_url_bucket_with_nested_prefix() -> None:
    cs = S3ColdStorage("s3://my-bucket/a/b/c")
    assert cs._bucket == "my-bucket"
    assert cs._prefix == "a/b/c/"


def test_s3_url_invalid_scheme_raises() -> None:
    with pytest.raises(ValueError, match="Invalid S3 bucket URL"):
        S3ColdStorage("https://my-bucket")
