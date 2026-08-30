"""Response envelopes shared across resources — defined once, reused by every
paginated/deletable resource rather than copy-pasted per-resource (Rules.md 1.7).
"""
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def create(cls, *, items: list[T], total: int, page: int, page_size: int) -> "Page[T]":
        # Exact-integer ceiling division, not math.ceil(total / page_size) — avoids
        # float precision entirely. 137 items at 20/page -> (137+19)//20 -> 7.
        pages = (total + page_size - 1) // page_size if page_size else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


class DeletedResponse(BaseModel):
    id: int
    deleted: bool = True
