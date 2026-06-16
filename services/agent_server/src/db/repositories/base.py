"""Generic async SQLAlchemy repository primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Generic, Optional, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..base import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseRepository(Generic[ModelT]):
    """Base repository with common CRUD helpers.

    Repositories commit writes by default. Services can opt into larger
    transactions by passing ``commit=False`` and committing explicitly.
    """

    model: type[ModelT]

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, entity_id: Any) -> Optional[ModelT]:
        """Return one entity by primary key, or ``None``."""
        return await self.db.get(self.model, entity_id)

    async def list(
        self,
        *,
        statement: Optional[Select[tuple[ModelT]]] = None,
    ) -> list[ModelT]:
        """Return entities for a custom statement, or all rows by default."""
        stmt = statement if statement is not None else select(self.model)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        data: Mapping[str, Any],
        *,
        commit: bool = True,
    ) -> ModelT:
        """Create an entity from mapping data."""
        entity = self.model(**dict(data))
        self.db.add(entity)
        if commit:
            await self.commit()
            await self.refresh(entity)
        else:
            await self.flush()
        return entity

    async def delete(
        self,
        entity_or_id: ModelT | Any,
        *,
        commit: bool = True,
    ) -> None:
        """Delete an entity or primary-key id."""
        entity = entity_or_id
        if not isinstance(entity_or_id, self.model):
            entity = await self.get(entity_or_id)
        if entity is None:
            return
        await self.db.delete(entity)
        if commit:
            await self.commit()
        else:
            await self.flush()

    async def add(
        self,
        entity: ModelT,
        *,
        commit: bool = True,
        refresh: bool = True,
    ) -> ModelT:
        """Add an already-built entity."""
        self.db.add(entity)
        if commit:
            await self.commit()
            if refresh:
                await self.refresh(entity)
        else:
            await self.flush()
        return entity

    async def add_all(
        self,
        entities: Sequence[ModelT],
        *,
        commit: bool = True,
    ) -> Sequence[ModelT]:
        """Add multiple entities."""
        self.db.add_all(list(entities))
        if commit:
            await self.commit()
        else:
            await self.flush()
        return entities

    async def flush(self) -> None:
        await self.db.flush()

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()

    async def refresh(self, entity: ModelT) -> None:
        await self.db.refresh(entity)
