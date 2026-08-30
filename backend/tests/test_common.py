"""Page[T]'s ceiling-division math, proven independently of any endpoint."""
from app.schemas.common import Page


def test_page_create_ceiling_division_137_at_20_gives_7():
    page = Page[int].create(items=[], total=137, page=1, page_size=20)
    assert page.pages == 7


def test_page_create_exact_multiple_does_not_overcount():
    page = Page[int].create(items=[], total=40, page=1, page_size=20)
    assert page.pages == 2


def test_page_create_empty_result_has_zero_pages():
    page = Page[int].create(items=[], total=0, page=1, page_size=20)
    assert page.pages == 0
    assert page.items == []
