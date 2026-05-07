"""Async SessionStore — DB CRUD for the sessions table."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.session.models import SessionRow


@dataclass
class SessionRecord:
    """Plain-data representation of a session row (no SQLAlchemy state attached)."""

    id: str
    session_id: str
    parent_id: str | None
    model: str
    provider: str
    input_json: dict[str, Any] | None
    output_json: dict[str, Any] | None
    usage_json: dict[str, Any] | None
    cold_storage_key: str | None
    created_at: datetime
    ttl_at: datetime | None

    @classmethod
    def from_row(cls, row: SessionRow) -> SessionRecord:
        """Build a SessionRecord from an ORM row.

        Auto-maps via dataclass fields so adding a column to SessionRow + this dataclass
        is a one-place change. If the schemas drift, this will raise TypeError loudly
        instead of silently dropping data.
        """
        return cls(**{f.name: getattr(row, f.name) for f in dataclasses.fields(cls)})

    def to_row(self) -> SessionRow:
        """Build an ORM row from a SessionRecord. See `from_row` for the auto-map rationale."""
        return SessionRow(**{f.name: getattr(self, f.name) for f in dataclasses.fields(self)})


class SessionStore:
    def __init__(self, db_url: str) -> None:
        self._engine = create_async_engine(db_url)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def create_schema(self, metadata: MetaData) -> None:
        """For tests only. Production uses Alembic migrations."""
        async with self._engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def insert(self, record: SessionRecord) -> None:
        async with self._sessionmaker() as session:
            session.add(record.to_row())
            await session.commit()

    async def get_by_id(self, response_id: str) -> SessionRecord | None:
        async with self._sessionmaker() as session:
            row = await session.get(SessionRow, response_id)
            return SessionRecord.from_row(row) if row else None

    async def list_by_session_id(self, session_id: str) -> list[SessionRecord]:
        async with self._sessionmaker() as session:
            stmt = (
                select(SessionRow)
                .where(SessionRow.session_id == session_id)
                .order_by(SessionRow.created_at.asc())
            )
            result = await session.execute(stmt)
            return [SessionRecord.from_row(r) for r in result.scalars().all()]

    async def delete_expired(self, as_of: datetime) -> int:
        async with self._sessionmaker() as session:
            stmt = delete(SessionRow).where(
                SessionRow.ttl_at.is_not(None), SessionRow.ttl_at < as_of
            )
            # AsyncSession.execute is typed as Result[Any], but DML statements
            # (DELETE/UPDATE) always produce a CursorResult at runtime — that is
            # the only Result subtype that exposes `rowcount`. The type:ignore
            # suppresses the inevitable assignment-narrow error on this line only.
            result: CursorResult[Any] = await session.execute(stmt)  # type: ignore[assignment]
            await session.commit()
            return result.rowcount or 0

    async def close(self) -> None:
        await self._engine.dispose()
