"""Async SessionStore — DB CRUD for the sessions table."""

from __future__ import annotations

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
        return cls(
            id=row.id,
            session_id=row.session_id,
            parent_id=row.parent_id,
            model=row.model,
            provider=row.provider,
            input_json=row.input_json,
            output_json=row.output_json,
            usage_json=row.usage_json,
            cold_storage_key=row.cold_storage_key,
            created_at=row.created_at,
            ttl_at=row.ttl_at,
        )

    def to_row(self) -> SessionRow:
        return SessionRow(
            id=self.id,
            session_id=self.session_id,
            parent_id=self.parent_id,
            model=self.model,
            provider=self.provider,
            input_json=self.input_json,
            output_json=self.output_json,
            usage_json=self.usage_json,
            cold_storage_key=self.cold_storage_key,
            created_at=self.created_at,
            ttl_at=self.ttl_at,
        )


class SessionStore:
    def __init__(self, db_url: str) -> None:
        self._engine = create_async_engine(db_url, future=True)
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
            result: CursorResult[Any] = await session.execute(stmt)  # type: ignore[assignment]
            await session.commit()
            return result.rowcount or 0

    async def close(self) -> None:
        await self._engine.dispose()
