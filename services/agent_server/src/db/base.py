"""SQLAlchemy declarative base.

Kept in its own module so both the ORM models and the Alembic ``env.py`` can
import :data:`Base` (and therefore ``Base.metadata``) without triggering the
database engine setup in ``database.py``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class BaseModel(DeclarativeBase):
    """Base class for all ORM models."""
