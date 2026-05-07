"""Tests for ID generation helpers."""

from __future__ import annotations

from gateway.ids import new_request_id, new_response_id, new_session_id


def test_response_id_has_resp_prefix() -> None:
    rid = new_response_id()
    assert rid.startswith("resp_")
    assert len(rid) > 30


def test_session_id_is_uuid_string() -> None:
    sid = new_session_id()
    assert isinstance(sid, str)
    assert len(sid) >= 32


def test_ids_are_unique() -> None:
    ids = {new_response_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_request_id_format() -> None:
    rid = new_request_id()
    assert isinstance(rid, str)
    assert len(rid) >= 32
