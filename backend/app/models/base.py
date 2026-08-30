"""Mixins and helpers shared by the model modules. Nothing here is a table
on its own.
"""
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    # onupdate is what makes this column actually move on every UPDATE —
    # without it, this is just a second created_at, and Phase 3's
    # stale-marking check on job edits depends on it changing.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def db_enum(enum_cls: type[Enum], length: int = 32) -> SAEnum[Any]:
    """SQLAlchemy Enum column type bound to a stdlib Enum from core/enums.py.

    SQLAlchemy's Enum type persists a Python Enum member's `.name` (e.g.
    "RECRUITER") by default, not its `.value` ("recruiter") — values_callable
    is what switches it to `.value`, which is what Architecture.md 9.6's
    "lowercase snake strings" promise actually depends on. native_enum=False
    renders a portable VARCHAR + CHECK constraint instead of a Postgres-only
    CREATE TYPE, so the same migration works on SQLite and PostgreSQL
    (Architecture.md 4).
    """
    return SAEnum(
        enum_cls,
        values_callable=lambda cls: [member.value for member in cls],
        native_enum=False,
        length=length,
        validate_strings=True,
    )
